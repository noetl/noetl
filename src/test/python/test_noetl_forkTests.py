from test_noetl import *


class TestNOETL_ForkTests(TestCase):
    """
        Fork Tests
    """

    """
            start
            /   \
           /     \
          /       \
    step1:        step2:cursor[1]
    cursor[1]


            exit
    """

    def test_simpleFork_1(self):
        # This one tests simple 2 forks without merge
        def asserts(allLines):
            self.assertEquals(2, len(allLines))
            if allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")):
                self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step2", "1")))
            else:
                self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")))

        sameSetupUp("noetlTest_simpleFork_1.json", asserts)

    """
            start
            /   \
           /     \
          /       \
    step1:        step2:cursor[1]
    cursor[1]      /
         \        /
          \      /
            exit
    """

    def test_simpleFork_2(self):
        # This one tests simple 2 forks merge at exit
        def asserts(allLines):
            self.assertEquals(2, len(allLines))
            if allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")):
                self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step2", "1")))
            else:
                self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")))

        sameSetupUp("noetlTest_simpleFork_2.json", asserts)

    """
            start
            /   \
           /     \
          /       \
    step1:        step2:cursor[1]
    cursor[1]      /
         \        /
          \      /
           \    /
           mergeStep: cursor[1]
             |
             |
            exit
    """

    def test_simpleFork_3(self):
        # This one tests simple 2 forks merge at exit
        def asserts(allLines):
            self.assertEquals(3, len(allLines))
            if allLines[0].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")):
                self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step2", "1")))
            else:
                self.assertTrue(allLines[1].startswith(SupportedTestActionsUtils.getPrefixString("step1", "1")))
            self.assertTrue(allLines[2].startswith(SupportedTestActionsUtils.getPrefixString("mergeStep", "1")))

        sameSetupUp("noetlTest_simpleFork_3.json", asserts)
