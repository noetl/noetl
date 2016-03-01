from Queue import *
from unittest import TestCase

from component.Step import *
from execution.QueueExecution import runCursorQueue
from util.NOETLJsonParser import NOETLJsonParser
from src.rootPath import TEST_RESOURCES


class TestRunThreadsProduction(TestCase):
    def test_runThreads_runShell_createFile_ValueInQueue_testMode(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1")
        queue = Queue()
        queue.put("2011-09-01")
        runCursorQueue(step, queue, True)
        self.assertEquals([], step.cursorFail)

    def test_runThreads_runShell_createFile_ValueInQueue(self):
        currentPath = os.path.dirname(os.path.abspath(__file__))

        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        config["WORKFLOW"]["TASKS"]["task1"]["STEPS"]["step1"]["CALL"]["EXEC"]["CMD"][0] = \
            [config["WORKFLOW"]["TASKS"]["task1"]["STEPS"]["step1"]["CALL"]["EXEC"]["CMD"][0][0]. \
                 replace("[%Y%m].test", os.path.join(currentPath, "[%Y%m].test"))]
        task = Task("task1", config)
        step = Step(task, "step1")
        queue = Queue()
        queue.put("2011-09-01")
        runCursorQueue(step, queue, False)
        self.assertEquals([], step.cursorFail)

        generatedFile = os.path.join(currentPath, "201109.test")
        with open(generatedFile) as f:
            all = f.readlines()
            self.assertEquals(1, len(all))
            self.assertEquals("Cursor 09/01/2011\n", all[0])
        os.remove(generatedFile)
