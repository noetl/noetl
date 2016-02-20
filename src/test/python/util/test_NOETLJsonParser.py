from unittest import TestCase
from src.rootPath import *
from src.main.python.util.NOETLJsonParser import NOETLJsonParser

__author__ = 'chenguo'


class TestNOETLJsonParser(TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testCurlyBraceReferences(self):
        varList = NOETLJsonParser.getCurlyBraceReferences("asdf${Hello}dfas${World}df")
        self.assertEqual(2, len(varList))
        self.assertEqual("Hello", varList[0])
        self.assertEqual("World", varList[1])

    def testGetGoodConfig(self):
        filePath = os.path.join(TEST_RESOURCES, "confExample1.json")
        conf = NOETLJsonParser(filePath).getConfig()
        self.assertEquals("localhost", conf["OS_ENV"]["HOST"])
        self.assertEquals("~/projects/github/noetl", conf["PROJECT"]["HOME"])
        loggingArray = conf["LOGGING"]
        for logConf in loggingArray:
            if isinstance(logConf, dict):
                name = logConf.get("NAME")
                file = logConf.get("FILE")
                if name is not None:
                    self.assertEquals("noetl", name)
                elif file is not None:
                    self.assertEquals("~/projects/github/noetl/log", file["DIRECTORY"])
            elif isinstance(logConf, basestring):
                self.assertEquals("FUN", logConf)

    def testGetBadConfig(self):
        filePath = os.path.join(TEST_RESOURCES, "confExample2_bad.json")
        with self.assertRaises(SystemExit):
            NOETLJsonParser(filePath).getConfig()
