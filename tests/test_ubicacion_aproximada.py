"""Geometría de posiciones aproximadas, sin confundirla con identidad confirmada."""

import copy
import math
import unittest

import numpy as np

from mapear_arboles import cargar_config
from mapeo.camaras import MarcoLocal, proyectar_observacion
from mapeo.localizacion import ajustar
from mapeo.ubicacion_aproximada import DEFAULTS, estimar_entidad, estimar_observacion


class UbicacionAproximadaTests(unittest.TestCase):
    def setUp(self):
        self.config = cargar_config()
        self.marco = MarcoLocal(-59.14, -37.335)
        self.meta = {"id": "1", "geometry": {"type": "Point", "coordinates": [-59.14, -37.335]},
                     "computed_rotation": [math.pi / 2, 0, 0], "computed_compass_angle": 0.,
                     "camera_type": "perspective", "camera_parameters": [.8, 0, 0],
                     "width": 2000, "height": 1200, "computed_altitude": 230.}

    def obs(self, caja, role="individual"):
        obs = {"id": "o1", "image_id": "1", "capture_id": "1", "epoch": "2018",
               "captured_at": 1000, "width": 2000, "height": 1200,
               "bbox_xyxy": caja, "role": role}
        obs["ray"] = proyectar_observacion(obs, self.meta, self.marco, self.config)
        return obs

    def test_pie_de_caja_a_diez_metros_se_proyecta_sobre_suelo(self):
        obs = self.obs([950, 0, 1049, 871.5])
        antes = copy.deepcopy(obs)
        punto = estimar_observacion(obs, self.meta, self.marco, self.config)
        self.assertEqual(punto["method"], "bbox_ground_plane")
        np.testing.assert_allclose(punto["xy"], [0, 10], atol=1e-6)
        np.testing.assert_allclose(self.marco.proyectar(*punto["coordinates"]), [0, 10], atol=1e-6)
        self.assertTrue(punto["is_approximate"])
        self.assertFalse(punto["used_for_identity"])
        self.assertEqual(punto["assumptions"]["camera_height_m"], 1.7)
        self.assertNotEqual(punto["assumptions"]["camera_height_m"], self.meta["computed_altitude"])
        self.assertEqual(obs, antes)

    def test_cerca_del_horizonte_prefiere_altura_aparente(self):
        obs = self.obs([950, 450, 1049, 610])
        punto = estimar_observacion(obs, self.meta, self.marco, self.config)
        self.assertEqual(punto["method"], "bbox_assumed_tree_height")
        self.assertAlmostEqual(punto["distance_m"], 80.)
        self.assertTrue(punto["assumptions"]["tree_height_is_assumed"])
        cfg = {**self.config, "approx_tree_height_m": 4.}
        self.assertAlmostEqual(estimar_observacion(obs, self.meta, self.marco, cfg)["distance_m"], 40.)

    def test_distancia_acotada_se_identifica_como_recortada(self):
        obs = self.obs([950, 570, 1049, 610])
        punto = estimar_observacion(obs, self.meta, self.marco, self.config)
        self.assertEqual(punto["distance_m"], self.config["max_range_m"])
        self.assertIn("distance_clamped_to_configured_range", punto["warnings"])
        self.assertGreater(punto["unclamped_distance_m"], punto["distance_m"])
        self.assertGreaterEqual(punto["uncertainty_m"], punto["distance_m"])

    def test_grupo_y_caja_cortada_no_suponen_altura_de_individuo(self):
        for obs in [self.obs([950, 450, 1049, 610], role="group"), self.obs([950, 200, 1049, 1200])]:
            punto = estimar_observacion(obs, self.meta, self.marco, self.config)
            self.assertEqual(punto["method"], "assumed_distance_along_ray")
            self.assertTrue(punto["assumptions"]["distance_is_assumed"])
            self.assertAlmostEqual(math.dist(punto["xy"], punto["camera_xy"]), 15.)
            self.assertGreaterEqual(punto["uncertainty_m"], 15.)

    def test_sin_calibracion_o_pose_no_se_inventa_posicion(self):
        obs = self.obs([950, 0, 1049, 871.5])
        for campo in ["camera_parameters", "computed_rotation", "geometry"]:
            meta = {k: v for k, v in self.meta.items() if k != campo}
            self.assertIsNone(estimar_observacion(obs, meta, self.marco, self.config))
        self.assertIsNone(estimar_observacion(obs, self.meta, None, self.config))
        self.assertIsNone(estimar_observacion({**obs, "role": "rejected"}, self.meta, self.marco, self.config))
        self.assertIsNone(estimar_observacion(obs, self.meta, self.marco, {**self.config, "allow_approximate_positions": False}))

    def test_posicion_previa_no_se_reemplaza_y_grupos_resueltos_no_se_recuentan(self):
        fit = {"xy": [3, 10], "method": "robust_bearing_intersection", "uncertainty_m": 3.}
        entidad = {"fit": fit, "observation_ids": []}
        copia = copy.deepcopy(entidad)
        p = estimar_entidad(entidad, {}, {}, self.marco, {**self.config, "allow_approximate_positions": False})
        self.assertEqual(p["xy"], [3, 10])
        self.assertFalse(p["is_approximate"])
        self.assertEqual(entidad, copia)
        self.assertIsNone(estimar_entidad({"status": "resolved"}, {}, {}, self.marco, self.config, grupo=True))

    def test_triangulacion_basica_usa_solo_evidencia_asociada_y_fechas_compatibles(self):
        observaciones = []
        for i, origen in enumerate([[0., 0.], [2., 0.]]):
            direccion = np.array([0., 50.]) - origen
            direccion /= np.linalg.norm(direccion)
            observaciones.append({"id": str(i), "capture_id": str(i), "image_id": str(i),
                                  "epoch": "2018", "captured_at": 1000 + i * 1000, "role": "individual",
                                  "ray": {"valid": True, "origin_xy": origen, "direction": direccion.tolist(),
                                          "bearing_deg": math.degrees(math.atan2(*direccion)) % 360,
                                          "uncertainty_deg": .1}})
        self.assertIsNone(ajustar(observaciones, self.config))  # Paralaje menor a los 5° originales.
        entidad = {"observation_ids": ["0", "1"]}
        p = estimar_entidad(entidad, {o["id"]: o for o in observaciones}, {}, self.marco, self.config)
        self.assertEqual(p["method"], "approximate_bearing_triangulation")
        np.testing.assert_allclose(p["xy"], [0, 50], atol=1e-6)
        self.assertFalse(p["used_for_identity"])
        observaciones[1]["epoch"] = "2020"
        self.assertIsNone(estimar_entidad(entidad, {o["id"]: o for o in observaciones}, {}, self.marco, self.config))

    def test_defaults_compatibles_con_relevamientos_anteriores(self):
        self.assertTrue(all(self.config[k] == v for k, v in DEFAULTS.items()))
        antigua = {k: v for k, v in self.config.items() if k not in DEFAULTS}
        obs = self.obs([950, 0, 1049, 871.5])
        self.assertIsNotNone(estimar_observacion(obs, self.meta, self.marco, antigua))


if __name__ == "__main__":
    unittest.main()
