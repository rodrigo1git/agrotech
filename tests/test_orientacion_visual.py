import math
import unittest

from mapeo.camaras import orientacion_visual
from mapeo.demo import registro_sintetico


class OrientacionVisualTests(unittest.TestCase):
    def test_preserva_cero_y_usa_heading_original_como_respaldo(self):
        self.assertEqual(orientacion_visual({'computed_compass_angle':0,'compass_angle':90})['bearing_deg'],0)
        self.assertEqual(orientacion_visual({'computed_compass_angle':None,'compass_angle':-90})['bearing_deg'],270)

    def test_extrae_rumbo_de_rotacion_si_no_hay_compas(self):
        meta=registro_sintetico('1',(0.,0.),[(13.,10.)])['mapillary']
        esperado=meta.pop('computed_compass_angle')
        self.assertAlmostEqual(orientacion_visual(meta)['bearing_deg'],esperado)
        self.assertEqual(orientacion_visual(meta)['source'],'computed_rotation')

    def test_no_inventa_orientacion_si_falta_o_camara_apunta_vertical(self):
        for meta in ({},{'computed_rotation':[0,0,0]},{'computed_rotation':[0,0]},
                     {'computed_compass_angle':math.nan,'compass_angle':math.inf}):
            self.assertIsNone(orientacion_visual(meta))


if __name__=='__main__':unittest.main()
