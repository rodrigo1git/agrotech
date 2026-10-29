"""Seguimiento visual básico, salvaguardas y reconciliación reversible."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mapear_arboles import cargar_config
from mapeo.almacen import Almacen
from mapeo.demo import registro_sintetico
from mapeo.inventario import reconciliar
from mapeo.seguimiento_visual import (
    ComparadorRecortes, cajas_compatibles, capturas_compatibles, crear_enlaces,
    fusionar_propuestas,
)


def observacion(oid, imagen, **extra):
    return {"id": oid, "image_id": imagen, "capture_id": imagen, "role": "individual",
            "width": 100, "height": 100, "bbox_xyxy": [10, 10, 60, 90],
            "epoch": "2018", "captured_at": 1539978452606,
            "ray": {"valid": False}, **extra}


def captura(i, **extra):
    return {"sequence": "seq", "captured_at": 1539978452606 + i * 1000,
            "geometry": {"type": "Point", "coordinates": [-59.14 + i * .00001, -37.33]},
            "computed_compass_angle": 0., "compass_angle": 90., **extra}


def propuesta(o, **extra):
    return {"observation_ids": [o["id"]], "identity_status": "candidate", "fit": None,
            "epoch": o["epoch"], "position_status": "unlocated", **extra}


def enlace(a, b):
    return {"a": a, "b": b, "score": .95}


class SeguimientoTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {**cargar_config(), "allow_visual_tracking": True}

    def test_compara_textura_real_y_rechaza_uniformes_y_otro_patron(self):
        with tempfile.TemporaryDirectory() as carpeta:
            rng = np.random.default_rng(21)
            patron = rng.integers(0, 255, (80, 50, 3), dtype=np.uint8)
            obs = []
            for i in range(4):
                foto = np.zeros((100, 100, 3), dtype=np.uint8)
                foto[10:90, 10:60] = patron if i < 2 else (rng.integers(0, 255, patron.shape, dtype=np.uint8) if i == 2 else 120)
                ruta = Path(carpeta) / f"{i}.png"
                Image.fromarray(foto).save(ruta)
                obs.append(observacion(str(i), str(i), image_path=str(ruta)))
            comparar = ComparadorRecortes()
            self.assertGreater(comparar(obs[0], obs[1])["score"], .99)
            self.assertLess(comparar(obs[0], obs[2])["score"], self.cfg["tracking_min_score"])
            self.assertIsNone(comparar(obs[0], obs[3]))
            obs[3]["id"] = "missing"
            obs[3]["image_path"] = str(Path(carpeta) / "missing.png")
            self.assertIsNone(comparar(obs[0], obs[3]))

    def test_filtros_recorrido_tiempo_posicion_y_giro_con_heading_cero(self):
        a, b = captura(0), captura(1)
        self.assertTrue(capturas_compatibles(a, b, self.cfg))
        for cambio in ({"sequence": "otra"}, {"captured_at": a["captured_at"]},
                       {"captured_at": a["captured_at"] + 6000},
                       {"computed_compass_angle": 20},
                       {"geometry": {"type": "Point", "coordinates": [-59.13, -37.33]}}):
            with self.subTest(cambio=cambio):
                self.assertFalse(capturas_compatibles(a, {**b, **cambio}, self.cfg))
        self.assertTrue(capturas_compatibles(a, {**b, "computed_compass_angle": 359}, self.cfg))

    def test_filtro_cajas(self):
        a = observacion("a", "1")
        self.assertTrue(cajas_compatibles(a, observacion("b", "2"), self.cfg))
        self.assertFalse(cajas_compatibles(a, observacion("b", "2", bbox_xyxy=[80, 10, 100, 90]), self.cfg))
        self.assertFalse(cajas_compatibles(a, observacion("b", "2", bbox_xyxy=[25, 25, 30, 30]), self.cfg))

    def test_asignacion_inequivoca_y_ambiguedad_con_rival_bajo_umbral(self):
        obs = [observacion("a", "1"), observacion("b", "2"), observacion("c", "2")]
        fotos = {"1": captura(0), "2": captura(1)}
        def comparar(a, b):
            return {"score": {"b": .95, "c": .70}[b["id"]]}
        self.assertEqual([(e["a"], e["b"]) for e in crear_enlaces(obs, fotos, self.cfg, comparar)], [("a", "b")])
        # .70 está debajo del mínimo .72, pero compite con .74: no es claro.
        def ambiguo(a, b):
            return {"score": {"b": .74, "c": .70}[b["id"]]}
        self.assertEqual(crear_enlaces(obs, fotos, self.cfg, ambiguo), [])

    def test_no_une_grupos_ni_dias_diferentes_y_cuenta_fotos_vacias(self):
        fotos = {str(i): captura(i) for i in range(4)}
        obs = [observacion("a", "0"), observacion("b", "3")]
        comparar = lambda a, b: {"score": .99}
        self.assertEqual(crear_enlaces(obs, fotos, self.cfg, comparar), [])
        self.assertEqual(len(crear_enlaces(obs, fotos, {**self.cfg, "tracking_frame_gap": 3}, comparar)), 1)
        obs[1]["role"] = "group"
        self.assertEqual(crear_enlaces(obs, fotos, {**self.cfg, "tracking_frame_gap": 3}, comparar), [])
        obs[1]["role"] = "individual"
        fotos = {"0": captura(0, captured_at=1540079999000), "3": captura(1, captured_at=1540080001000)}
        self.assertTrue(capturas_compatibles(fotos["0"], fotos["3"], self.cfg))
        self.assertEqual(crear_enlaces(obs, fotos, self.cfg, comparar), [])
        self.assertEqual(crear_enlaces(obs, fotos, {**self.cfg, "allow_visual_tracking": False}, comparar), [])

    def fusion(self, obs, edges, anteriores=None, propuestas=None):
        return fusionar_propuestas(propuestas or [propuesta(o) for o in obs], obs, edges,
                                  anteriores or {"trees": []}, self.cfg)

    def test_fusion_transitiva_rechaza_dos_arboles_visibles_juntos(self):
        obs = [observacion("a", "1"), observacion("b", "2"), observacion("c", "1")]
        resultado, informe = self.fusion(obs, [enlace("a", "b"), enlace("b", "c")])
        self.assertEqual(len(resultado), 2)
        self.assertEqual(informe["merges"], 1)
        self.assertEqual(informe["rejected"][0]["reason"], "distinct_trees_visible_in_same_capture")
        unido = next(p for p in resultado if len(p["observation_ids"]) == 2)
        self.assertEqual(unido["identity_status"], "candidate")
        self.assertEqual(unido["visual_tracking"]["images"], 2)
        self.assertFalse(unido["visual_tracking"]["confirmed"])

    def test_respeta_identidades_revisadas_y_confirmadas(self):
        obs = [observacion("a", "1"), observacion("b", "2")]
        for extra in ({"origin": "review"}, {"identity_status": "confirmed"}):
            resultado, informe = self.fusion(obs, [enlace("a", "b")], {"trees": [{**propuesta(obs[0]), **extra}]})
            self.assertEqual(len(resultado), 2)
            self.assertEqual(informe["rejected"][0]["reason"], "protected_identity")

    def test_no_descarta_geometria_ni_asocia_otra_epoca_o_grupos(self):
        obs = [observacion("a", "1"), observacion("b", "2")]
        pp = [propuesta(obs[0], fit={"xy": [1, 1]}), propuesta(obs[1])]
        resultado, informe = self.fusion(obs, [enlace("a", "b")], propuestas=pp)
        self.assertEqual(len(resultado), 2)
        self.assertEqual(informe["rejected"][0]["reason"], "would_discard_existing_geometry")
        obs[1]["epoch"] = "2019"
        self.assertEqual(self.fusion(obs, [enlace("a", "b")])[1]["merges"], 0)
        self.assertEqual(self.fusion(obs, [enlace("a", "grupo")])[1]["rejected"][0]["reason"], "unresolved_or_group_observation")

    def test_reconciliar_es_estable_y_desactivable_conserva_detecciones_y_auditoria(self):
        with tempfile.TemporaryDirectory() as carpeta:
            almacen = Almacen(Path(carpeta) / "inventario.sqlite")
            try:
                survey = almacen.survey("prueba", self.cfg)
                # Cámaras sin baseline: geometría sola deja dos candidatos.
                for i in range(2):
                    almacen.importar("prueba", registro_sintetico(str(i), (3., 0.), [(12., 10.)], verified=False))
                raw = copy.deepcopy(almacen.observaciones("prueba"))
                off = {**self.cfg, "allow_visual_tracking": False}
                reconciliar(almacen, survey, off)
                def enlaces(obs, capturas, config):
                    return [enlace(obs[0]["id"], obs[1]["id"])]
                with patch("mapeo.seguimiento_visual.crear_enlaces", side_effect=enlaces):
                    nuevo = reconciliar(almacen, survey, self.cfg)
                    estado = almacen.estado("prueba")
                    self.assertEqual(sum(t["active"] for t in estado["trees"]), 1)
                    self.assertEqual(nuevo["tracking_report"]["merges"], 1)
                    self.assertIsNone(reconciliar(almacen, survey, self.cfg)["event_id"])
                    self.assertEqual(almacen.estado("prueba"), estado)
                    almacen.deshacer("prueba", nuevo["event_id"])
                    self.assertEqual(sum(t["active"] for t in almacen.estado("prueba")["trees"]), 2)
                    reconciliar(almacen, survey, self.cfg)
                reconciliar(almacen, survey, off)
                self.assertEqual(sum(t["active"] for t in almacen.estado("prueba")["trees"]), 2)
                self.assertEqual(almacen.observaciones("prueba"), raw)
            finally:
                almacen.close()


if __name__ == "__main__":
    unittest.main()
