import os
from unittest import TestCase

from src.rootPath import TEST_RESOURCES
from util.Tools import *
from util.NOETLJsonParser import NOETLJsonParser


class TestTools(TestCase):
    def test_processConfRequest(self):
        filePath = os.path.join(TEST_RESOURCES, "confExample1.json")
        conf = NOETLJsonParser(filePath).getConfig()
        self.assertEquals("localhost", processConfRequest(conf, "OS_ENV.HOST"))
        self.assertEquals("FUN", processConfRequest(conf, "LOGGING.1"))
        self.assertEquals("noetl", processConfRequest(conf, "LOGGING.0.NAME"))
        self.assertEquals([0, 1], processConfRequest(conf, "LOGGING", True))

    def test_getDateCursor1(self):
        cursor = getCursor(["2011-09-01:2011-12-31"], "date", "1M", "%Y-%m-%d")
        self.assertEquals(['2011-09-01', '2011-10-01', '2011-11-01', '2011-12-01'], cursor)

    def test_getDateCursor2(self):
        cursor = getCursor(["2011-09-01:2011-10-31", "2011-07-01"], "date", "1M", "%Y-%m-%d")
        self.assertEquals(['2011-07-01', '2011-09-01', '2011-10-01'], cursor)

    def test_getIntegerCursor1(self):
        cursor = getCursor(["1:4"], "integer", "2", "")
        self.assertEquals(['1', '3'], cursor)

    def test_getIntegerCursor2(self):
        cursor = getCursor(["1:5"], "integer", "2", "")
        self.assertEquals(['1', '3', '5'], cursor)

    # ??
    # Should we expect an order by NUMBER rather than by STRING?
    def test_getIntegerCursor3(self):
        cursor = getCursor(["1:4", '10'], "integer", "2", "")
        self.assertEquals(['1', '10', '3'], cursor)

    def test_getIntegerCursor4(self):
        cursor = getCursor(["1:4", '3'], "integer", "2", "")
        self.assertEquals(['1', '3'], cursor)
