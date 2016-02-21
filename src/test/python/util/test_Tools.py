from unittest import TestCase

from util import Tools


class TestTools(TestCase):
    def test_getDateCursor1(self):
        cursor = Tools.getCursor(["2011-09-01:2011-12-31"], "date", "1M", "%Y-%m-%d")
        self.assertEquals(['2011-09-01', '2011-10-01', '2011-11-01', '2011-12-01'], cursor)

    def test_getDateCursor2(self):
        cursor = Tools.getCursor(["2011-09-01:2011-10-31", "2011-07-01"], "date", "1M", "%Y-%m-%d")
        self.assertEquals(['2011-07-01', '2011-09-01', '2011-10-01'], cursor)

    def test_getIntegerCursor1(self):
        cursor = Tools.getCursor(["1:4"], "integer", "2", "")
        self.assertEquals(['1', '3'], cursor)

    def test_getIntegerCursor2(self):
        cursor = Tools.getCursor(["1:5"], "integer", "2", "")
        self.assertEquals(['1', '3', '5'], cursor)

    # Should we expect an order by NUMBER rather than by STRING?
    def test_getIntegerCursor3(self):
        cursor = Tools.getCursor(["1:4", '10'], "integer", "2", "")
        self.assertEquals(['1', '10', '3'], cursor)

    def test_getIntegerCursor4(self):
        cursor = Tools.getCursor(["1:4", '3'], "integer", "2", "")
        self.assertEquals(['1', '3'], cursor)
