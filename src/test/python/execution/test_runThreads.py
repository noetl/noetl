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
        self.assertEquals(0, runThreads(config, step, Queue()))

    def test_runThreads_doTestJob(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = ExpandedStep(task, "step1", config)
        queue = Queue()
        queue.put("0")
        queue.put("1")
        queue.put("2")
        self.assertEquals(0, runThreads(config, step, queue))
        self.assertTrue('0' in step.successfulCursors)
        self.assertTrue('1' in step.successfulCursors)
        self.assertTrue('2' in step.successfulCursors)

    def test_runThreads_runShell_createFile_NoneInQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        queue = Queue()
        queue.put(None)
        self.assertEquals(0, runThreads(config, step, queue))
        self.assertEquals([None], step.cursorFail)

    def test_runThreads_runShell_createFile_ValueInQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest_createFile.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        queue = Queue()
        queue.put("2011-09-01")
        self.assertEquals(0, runThreads(config, step, queue))
        self.assertEquals([], step.cursorFail)
