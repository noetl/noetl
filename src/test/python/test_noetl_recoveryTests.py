import os
from unittest import TestCase

import TestUtils
from src.main.python.execution.ExecutionActionsForTests import SupportedTestActionsUtils
from src.main.python.noetl import *
from src.rootPath import TEST_RESOURCES


class TestNOETL_RecoveryTests(TestCase):
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

        TestUtils.sameSetupUp("noetlTest_simple3StepFailure_1.json", asserts)

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

        TestUtils.sameSetupUp("noetlTest_simple3StepFailure_2.json", asserts)

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

        TestUtils.sameSetupUp("noetlTest_simple3StepFailure_3.json", asserts)

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
            self.assertEquals(4, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[3].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))

        TestUtils.sameSetupUp("noetlTest_simple3StepFailure_4.json", asserts)

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

        TestUtils.sameSetupUp("noetlTest_simple3StepFailure_5.json", asserts)

    """
   step1: cursor[-1], MaxFailure:1, Inherit: False
     |  \
     |   \F
     |    \
     |   step1_recovery: cursor[1],  MaxFailure:1, Inherit: False
    S|   /  |   \
     |  /   |    \S
     | /F   |     \__step1_recovery_fork2: cursor[1],  MaxFailure:1, Inherit: False
     |/     |S                                                                   |
     |      |                                                                    |
     |     step1_recovery_fork1: cursor[1],  MaxFailure:1, Inherit: False        |SF
     |     /                                                                     /
     |    /SF           ________________________________________________________/
     |   /_____________/
     |  /
     exit
   """

    def test_simple3StepFailure_6(self):
        # Test that the recovery branch fork is not allowed.
        # The program should stop at step1_recovery.
        def asserts(allLines):
            self.assertEquals(1, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))

        TestUtils.sameSetupUp("noetlTest_simple3StepFailure_disallow1.json", asserts)

    """
    step1: cursor[-1], MaxFailure:1, Inherit: False
      |     \                                     /\_________
      |      \F                                              \_________
      |S      \/                                                       \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False    |S
      |    /    \                                                      /
      |   /F     \/S                                                   /
      |  /    step2_recovery: cursor[1],  MaxFailure:1, Inherit: False
      | /    /
      |/    /
      |    /
      |   /F
     \|/\/
     exit
    """

    def test_simple4StepFailure_1(self):
        # This one tests 2-step recovery
        def asserts(allLines):
            self.assertEquals(4, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step2_recovery", "1")))
            self.assertTrue(allLines[3].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))

        TestUtils.sameSetupUp("noetlTest_simple4StepFailure_1.json", asserts)

    """
    step1: cursor[-1], MaxFailure:1, Inherit: False
      |     \                                     /\_________
      |      \F                                              \_________
      |S      \/                                                       \
      |     step1_recovery: cursor[1],  MaxFailure:1, Inherit: False    |S
      |    /    \                                                      /
      |   /F     \/S                                                   /
      |  /    step2_recovery: cursor[-1],  MaxFailure:1, Inherit: False
      | /    /
      |/    /
      |    /
      |   /F
     \|/\/
     exit
    """

    def test_simple4StepFailure_2(self):
        # This one tests 2-step recovery
        def asserts(allLines):
            self.assertEquals(3, len(allLines))
            self.assertTrue(allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "-1")))
            self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1_recovery", "1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("step2_recovery", "-1")))

        TestUtils.sameSetupUp("noetlTest_simple4StepFailure_2.json", asserts)
