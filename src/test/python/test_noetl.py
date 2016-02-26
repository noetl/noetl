import os
from unittest import TestCase
from src.main.python.execution.ExecutionActionsForTests import SupportedTestActionsUtils
from src.main.python.noetl import *
from src.rootPath import TEST_RESOURCES


class TestNOETL(TestCase):
    def test_goThroughMostBasic(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_mostBasic.json")
        main([None, filePath])

    def __sameSetupUp(self, fileName, asserts):
        filePath = os.path.join(TEST_RESOURCES, fileName)
        generatedFile = os.path.join(TEST_RESOURCES, "ChenTestGeneratedFile")
        if os.path.exists(generatedFile):
            os.remove(generatedFile)
        main([None, filePath])
        with open(generatedFile) as f:
            all = f.readlines()
            print(os.linesep)
            print(os.linesep.join(all))
            asserts(all)
        os.remove(generatedFile)

    """
    step1: cursor[-1], MaxFailure:1, Inherit: False
      |     \
      |      \F
      |S      \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False
      |     /
      |    /SF
      |   /
    exit
    """

    def test_simple3StepFailure_1(self):
        def asserts(allLines):
            self.assertEquals(2, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))

        self.__sameSetupUp("noetlTest_simple3StepFailure_1.json", asserts)

    """
    step1: cursor[-1], MaxFailure:1, Inherit: False
      |     \
      |      \F
      |S      \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: True
      |     /
      |    /SF
      |   /
    exit
    """

    def test_simple3StepFailure_2(self):
        # This one tests cursor inheritance
        def asserts(allLines):
            self.assertEquals(2, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "-1")))

        self.__sameSetupUp("noetlTest_simple3StepFailure_2.json", asserts)

    """
    step1: cursor[-1], MaxFailure:1, Inherit: False
      |     \      /\
      |      \F      \ S
      |S      \/      \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False
      |     /
      |    /F
      |  \/
    exit
    """

    def test_simple3StepFailure_3(self):
        # This one tests recovery success.
        def asserts(allLines):
            self.assertEquals(3, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))

        self.__sameSetupUp("noetlTest_simple3StepFailure_3.json", asserts)
