import unittest

from lib.metrics import MetricsParser


class MetricsParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = MetricsParser()

    def test_metric_parser(self):
        message = """<14>1 - 10:9c:70:28:65:4a buddy - - - msg=2316209,tm=636135566906,v=4 heater_current v=0.040304 -76
pos_x v=202.000000 8843
pos_y v=211.000000 8896
pos_z v=168.000000 8900
pos_x v=202.000000 20891
pos_y v=211.000000 20898
pos_z v=168.000000 20903
filament v="PETG" 22877
pos_x v=202.000000 32891
pos_y v=211.000000 32897
pos_z v=168.000000 32902
pos_x v=202.000000 44874
pos_y v=211.000000 44881
pos_z v=168.000000 44892
pos_x v=202.000000 56875
pos_y v=211.000000 56882
pos_z v=168.000000 56892
stp_stall v=1234i 60892
sdpos v=390191i 60899
cmdcnt v=1391388i 60903
heap free=63160i,total=81960i 63917
tmc_read error="value too long" 40039
tmc_read,ax=? reg=106i,regn="mscnt",value=1008i 40133
pos_x v=202.000000 68844
pos_y v=211.000000 68850
pos_z v=168.000000 68855
pos_x v=202.000000 79888
pos_y v=211.000000 79895
pos_z v=168.000000 79900
pos_x v=202.000000 91891
pos_y v=211.000000 91898
pos_z v=168.000000 91903
pos_x v=202.000000 103890
pos_y v=211.000000 103897
pos_z v=168.000000 103901
pos_x v=202.000000 115890
pos_y v=211.000000 115896
pos_z v=168.000000 115901
"""
        metrics = self.parser.parse_message(message)
        map = {}
        for metric in metrics:
            for key, value in metric.values.items():
                map[metric.name + "-" + key] = value
        self.assertEqual(map["tmc_read-error"], "value too long")
        self.assertEqual(map["tmc_read,ax=?-regn"], "mscnt")
        self.assertEqual(map["tmc_read,ax=?-value"], 1008)
        self.assertEqual(map["pos_z-v"], 168.0)
