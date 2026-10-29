"""Límite lateral en metros y referencia local, sin consultas a mapas."""

import copy
import math
import unittest

import numpy as np

from mapear_arboles import cargar_config
from mapeo.camaras import MarcoLocal
from mapeo.limite_lateral import ejes_de_camaras, limitar_posicion


class LimiteLateralTests(unittest.TestCase):
    def setUp(self):
        self.config = cargar_config()
        self.marco = MarcoLocal(-59.14, -37.335)
        self.ejes = {"1": {"origin_xy": [0., 0.], "direction": [0., 1.],
                            "source": "capture_trajectory", "reference_image_ids": ["1", "2"]}}

    def punto(self, xy):
        return {"xy": xy, "is_approximate": True, "uncertainty_m": 10.,
                "source_image_ids": ["1"], "method": "bbox_assumed_tree_height", "warnings": []}

    def meta(self, xy, fecha=1539978452606, secuencia="A"):
        return {"computed_geometry": {"type": "Point", "coordinates": self.marco.geografica(*xy)},
                "computed_rotation": [math.pi / 2, 0., 0.], "computed_compass_angle": 0.,
                "captured_at": fecha, "sequence": secuencia}

    def test_limita_ambos_lados_sobre_el_mismo_rayo_sin_reducir_incertidumbre(self):
        for lado in [-1, 1]:
            p = self.punto([lado * 20., 100.])
            original = copy.deepcopy(p)
            q = limitar_posicion(p, self.ejes, self.marco, self.config)
            np.testing.assert_allclose(q["xy"], [lado * 6., 30.])
            self.assertAlmostEqual(abs(q["lateral_constraint"]["lateral_after_m"]), 6.)
            self.assertEqual(math.copysign(1, q["xy"][0]), lado)
            self.assertAlmostEqual(q["xy"][0] * p["xy"][1] - p["xy"][0] * q["xy"][1], 0.)
            self.assertGreaterEqual(q["uncertainty_m"], p["uncertainty_m"])
            self.assertGreaterEqual(q["uncertainty_m"], q["lateral_constraint"]["adjustment_m"])
            self.assertEqual(p, original)
            self.assertEqual(q["lateral_constraint"]["raw_xy"], original["xy"])

    def test_no_es_un_radio_de_seis_metros_ni_cambia_posiciones_dentro_del_limite(self):
        p = self.punto([3., 80.])
        q = limitar_posicion(p, self.ejes, self.marco, self.config)
        np.testing.assert_allclose(q["xy"], p["xy"])
        self.assertGreater(q["distance_m"], 80.)
        self.assertFalse(q["lateral_constraint"]["applied"])

    def test_respeta_eje_rotado_y_limite_configurable(self):
        ejes = {"1": {**self.ejes["1"], "origin_xy": [5., 4.], "direction": [1., 0.]}}
        q = limitar_posicion(self.punto([105., 24.]), ejes, self.marco,
                             {**self.config, "approx_max_lateral_distance_m": 3.})
        np.testing.assert_allclose(q["xy"], [20., 7.])
        self.assertAlmostEqual(q["lateral_constraint"]["lateral_after_m"], 3.)
        np.testing.assert_allclose(self.marco.proyectar(*q["coordinates"]), q["xy"], atol=1e-6)

    def test_desactivado_o_posicion_previa_no_se_modifican(self):
        p = self.punto([20., 100.])
        self.assertIs(limitar_posicion(p, self.ejes, self.marco, {**self.config, "allow_lateral_limit": False}), p)
        p["is_approximate"] = False
        self.assertIs(limitar_posicion(p, self.ejes, self.marco, self.config), p)
        self.assertIsNone(limitar_posicion(None, self.ejes, self.marco, self.config))

    def test_aplicacion_repetida_conserva_punto_original(self):
        p = limitar_posicion(self.punto([20., 100.]), self.ejes, self.marco, self.config)
        self.assertEqual(limitar_posicion(p, self.ejes, self.marco, self.config), p)
        q = limitar_posicion(p, self.ejes, self.marco, {**self.config, "approx_max_lateral_distance_m": 10.})
        np.testing.assert_allclose(q["xy"], [10., 50.])
        self.assertEqual(q["lateral_constraint"]["raw_xy"], [20., 100.])

    def test_referencia_es_trayectoria_local_y_no_rumbo_de_camara(self):
        metas = {"1": self.meta([0., 0.]), "2": self.meta([10., 0.], 1539978453606),
                 "3": self.meta([10., 10.], 1539978454606), "4": self.meta([10., 20.], 1539978455606)}
        ejes = ejes_de_camaras(metas, self.marco, self.config)
        np.testing.assert_allclose(ejes["1"]["direction"], [1., 0.], atol=1e-7)
        np.testing.assert_allclose(ejes["3"]["direction"], [0., 1.], atol=1e-7)
        self.assertEqual(ejes["3"]["reference_image_ids"], ["2", "3", "4"])
        self.assertEqual(ejes["1"]["source"], "capture_trajectory")

    def test_no_mezcla_secuencias_anos_o_camaras_sin_separacion(self):
        for segunda in [self.meta([20., 0.], secuencia="B"),
                         self.meta([20., 0.], fecha=1600000000000),
                         self.meta([0., 0.])]:
            ejes = ejes_de_camaras({"1": self.meta([0., 0.]), "2": segunda}, self.marco, self.config)
            self.assertEqual(ejes["1"]["source"], "camera_heading_assumed_travel_direction")
            np.testing.assert_allclose(ejes["1"]["direction"], [0., 1.], atol=1e-7)

    def test_sin_referencia_no_inventa_eje(self):
        ejes = ejes_de_camaras({"1": {"geometry": {"type": "Point", "coordinates": [-59.14, -37.335]}}},
                               self.marco, self.config)
        self.assertEqual(ejes, {})
        p = self.punto([20., 100.])
        q = limitar_posicion(p, ejes, self.marco, self.config)
        self.assertEqual(q["xy"], p["xy"])
        self.assertIn("lateral_reference_unavailable", q["warnings"])


if __name__ == "__main__":
    unittest.main()
