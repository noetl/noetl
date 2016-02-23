import os
from Queue import *
from unittest import TestCase
from src.main.python.component.Step import *
from src.main.python.execution.QueueExecution import runThreads
from src.main.python.util.NOETLJsonParser import NOETLJsonParser
from src.rootPath import TEST_RESOURCES


class ExpandedStep(Step):
    def __init__(self, taskParent, stepName, config):
        Step.__init__(self, taskParent, stepName, config)
        self.successfulCursors = []


class TestRunThreads(TestCase):
    def test_runThreads_emptyQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        self.assertEquals(0, runThreads(config, step, Queue(), True))

    def test_runThreads_doTestJob_testMode(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = ExpandedStep(task, "step1", config)
        queue = Queue()
        queue.put("0")
        queue.put("1")
        queue.put("2")
        self.assertEquals(0, runThreads(config, step, queue, True))
        self.assertTrue('0' in step.successfulCursors)
        self.assertTrue('1' in step.successfulCursors)
        self.assertTrue('2' in step.successfulCursors)

    def test_runThreads_doTestJob(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = ExpandedStep(task, "step1", config)
        queue = Queue()
        queue.put("0")
        queue.put("1")
        queue.put("2")
        self.assertEquals(0, runThreads(config, step, queue, False))
        self.assertTrue('0Done' in step.successfulCursors)
        self.assertTrue('1Done' in step.successfulCursors)
        self.assertTrue('2Done' in step.successfulCursors)

    def test_runThreads_runShell_createFile_NoneInQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        queue = Queue()
        queue.put(None)
        self.assertEquals(0, runThreads(config, step, queue, True))
        self.assertEquals([None], step.cursorFail)

    def test_runThreads_runShell_createFile_ValueInQueue_testMode(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        queue = Queue()
        queue.put("2011-09-01")
        self.assertEquals(0, runThreads(config, step, queue, True))
        self.assertEquals([], step.cursorFail)

    def test_runThreads_runShell_createFile_ValueInQueue(self):
        currentPath = os.path.dirname(os.path.abspath(__file__))

        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        config["WORKFLOW"]["TASKS"]["task1"]["STEPS"]["step1"]["CALL"]["EXEC"]["CMD"][0] = \
            [config["WORKFLOW"]["TASKS"]["task1"]["STEPS"]["step1"]["CALL"]["EXEC"]["CMD"][0][0]. \
                 replace("[%Y%m].test", os.path.join(currentPath, "[%Y%m].test"))]
        task = Task("task1", config)
        step = Step(task, "step1", config)
        queue = Queue()
        queue.put("2011-09-01")
        self.assertEquals(0, runThreads(config, step, queue, False))
        self.assertEquals([], step.cursorFail)

        generatedFile = os.path.join(currentPath, "201109.test")
        with open(generatedFile) as f:
            all = f.readlines()
            self.assertEquals(1, len(all))
            self.assertEquals("Cursor 09/01/2011\n", all[0])
        os.remove(generatedFile)
