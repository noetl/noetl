import os
from Queue import *
from unittest import TestCase
from src.main.python.component.Step import *
from src.main.python.execution.QueueExecution import runThreads
from src.main.python.util.NOETLJsonParser import NOETLJsonParser
from src.rootPath import TEST_RESOURCES


class ExpandedStep(Step):
    def __init__(self, task, stepName):
        Step.__init__(self, task, stepName)
        self.successfulCursors = []


class TestRunThreadsTest(TestCase):
    def test_runThreads_emptyQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1")
        runThreads(step, Queue(), True)

    def test_runThreads_doTestJob_testMode(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = ExpandedStep(task, "step1")
        queue = Queue()
        queue.put("0")
        queue.put("1")
        queue.put("2")
        runThreads(step, queue, True)
        self.assertTrue('0' in step.successfulCursors)
        self.assertTrue('1' in step.successfulCursors)
        self.assertTrue('2' in step.successfulCursors)
        self.assertEquals([], step.cursorFail)

    def test_runThreads_doTestJob_testMode_multiThreads(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_multiThreads.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = ExpandedStep(task, "step1")
        testRange = [str(i) for i in range(0, 10)]
        queue = Queue()
        for i in testRange:
            queue.put(i)
        runThreads(step, queue, True)
        for i in testRange:
            self.assertTrue(i in step.successfulCursors)
        print(step.cursorFail)

    def test_runThreads_doTestJob(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = ExpandedStep(task, "step1")
        queue = Queue()
        queue.put("0")
        queue.put("1")
        queue.put("2")
        runThreads(step, queue, False)
        self.assertTrue('0Done' in step.successfulCursors)
        self.assertTrue('1Done' in step.successfulCursors)
        self.assertTrue('2Done' in step.successfulCursors)
        self.assertEquals([], step.cursorFail)

    def test_runThreads_runShell_createFile_NoneInQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1")
        queue = Queue()
        queue.put(None)
        runThreads(step, queue, True)
        self.assertEquals([None], step.cursorFail)
