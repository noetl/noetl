from unittest import TestCase

from src.main.python.util.EvalJsonParser import EvalJsonParser

__author__ = 'chenguo'


class TestEvalJsonParse(TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testGetConfig1(self):

        EvalJsonParser("/Users/chenguo/Documents/noetl/noetl/conf/coursor.inherit.cfg.v1.json").getConfig()
