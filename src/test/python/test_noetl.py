import os
from unittest import TestCase
from src.main.python.execution.ExecutionActionsForTests import SupportedTestActionsUtils
from src.main.python.noetl import *
from src.rootPath import TEST_RESOURCES


def sameSetupUp(fileName, asserts):
    filePath = os.path.join(TEST_RESOURCES, fileName)
    generatedFile = os.path.join(TEST_RESOURCES, "ChenTestGeneratedFile")
    if os.path.exists(generatedFile):
        os.remove(generatedFile)
    main([None, filePath])
    with open(generatedFile) as f:
        allLines = f.readlines()
        print(os.linesep)
        print(os.linesep.join(allLines))
        asserts(allLines)
    os.remove(generatedFile)


class TestNOETL(TestCase):
    def test_goThroughMostBasic(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_mostBasic.json")
        main([None, filePath])

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

        sameSetupUp("noetlTest_simple3StepFailure_1.json", asserts)

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

        sameSetupUp("noetlTest_simple3StepFailure_2.json", asserts)

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
        # This one tests 1-step recovery.
        def asserts(allLines):
            self.assertEquals(3, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))

        sameSetupUp("noetlTest_simple3StepFailure_3.json", asserts)

    """
    step1: cursor[-1], MaxFailure:2, Inherit: False
      |     \      /\
      |      \F      \ S
      |S      \/      \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False
      |     /
      |    /F
      |  \/
    exit
    """

    def test_simple3StepFailure_4(self):
        # This one tests 1-step recovery allowing 2 MaxFailures for failed step
        def asserts(allLines):
            self.assertEquals(5, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[3].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[4].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))

        sameSetupUp("noetlTest_simple3StepFailure_4.json", asserts)

    """
    step1: cursor[-2:2], MaxFailure:1, Inherit: False
      |     \      /\
      |      \F      \ S
      |S      \/      \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False
      |     /
      |    /F
      |  \/
    exit
    """

    def test_simple3StepFailure_5(self):
        # This one tests that only failed cursors will be picked for next step run.
        def asserts(allLines):
            self.assertEquals(9, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-2")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step1", "0")))
            self.assertTrue(allLines[3].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")))
            self.assertTrue(allLines[4].startswith(SupportedTestActionsUtils.getPrefixString("step1", "2")))
            self.assertTrue(allLines[5].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[6].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[7].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-2")))
            self.assertTrue(allLines[8].startswith(SupportedTestActionsUtils.getPrefixString("step1", "0")))

        sameSetupUp("noetlTest_simple3StepFailure_5.json", asserts)
