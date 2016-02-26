import os
from unittest import TestCase

from src.main.python.execution.ExecutionActionsForTests import SupportedTestActionsUtils
from src.main.python.noetl import *
from src.rootPath import TEST_RESOURCES


class TestNOETL(TestCase):
    def test_goThroughMostBasic(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_mostBasic.json")
        main([None, filePath])

    def test_goThroughBasicFailure(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_simple3StepFailure.json")
        generatedFile = os.path.join(TEST_RESOURCES, "ChenTestGeneratedFile")
        if os.path.exists(generatedFile):
            os.remove(generatedFile)
        main([None, filePath])
        with open(generatedFile) as f:
            all = f.readlines()
            print(os.linesep)
            print(os.linesep.join(all))
            self.assertEquals(2, len(all))
            self.assertTrue(all[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(all[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
        os.remove(generatedFile)
