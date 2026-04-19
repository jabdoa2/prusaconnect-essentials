import unittest

from lib.logs import LogParser, LogLine


class LogParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = LogParser()

    def test_log_parser(self):
        log1 = b"<14>1 - 11:11:11:11:11:11 buddy Marlin - - SD printing byte 3159448/3921027"
        parsed_log1 = self.parser.parse_message(log1.decode())
        self.assertIsInstance(parsed_log1, LogLine)
        log2 = b"<14>1 - 11:11:11:11:11:11 buddy USBDevice - - CDC write timeout, unlocking after 3000ms"
        parsed_log2 = self.parser.parse_message(log2.decode())
        self.assertIsInstance(parsed_log2, LogLine)
        log3 = b"<12>1 - 11:11:11:11:11:11 buddy Loadcell - - Loadcell metrics overflow"
        parsed_log3 = self.parser.parse_message(log3.decode())
        self.assertIsInstance(parsed_log3, LogLine)
        log4 = b"<14>1 - 11:11:11:11:11:11 buddy Marlin - - PCE-Trigger: snapshot()"
        parsed_log4 = self.parser.parse_message(log4.decode())
        self.assertIsInstance(parsed_log4, LogLine)
        log5 = b"<14>1 - 11:11:11:11:11:11 buddy Marlin - - X:88.91 Y:175.39 Z:3.20 E:0.00 Count A:21633 B:-13644 Z:1378"
        parsed_log5 = self.parser.parse_message(log5.decode())
        self.assertIsInstance(parsed_log5, LogLine)
