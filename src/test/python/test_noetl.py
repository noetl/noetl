import os
from unittest import TestCase

from src.main.python.execution.ExecutionActionsForTests import SupportedTestActionsUtils
from src.main.python.noetl import *
from src.rootPath import TEST_RESOURCES


class TestNOETL(TestCase):
    def test_goThroughMostBasic(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_mostBasic.json")
        main([None, filePath])

    """
    step1: cursor[-1], MaxFailure:1
      |     \
      |      \F
      |S      \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False
      |     /
      |    /SF
      |   /
    exit
    """

    def test_goThroughBasicFailure_1(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_simple3StepFailure_1.json")
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
