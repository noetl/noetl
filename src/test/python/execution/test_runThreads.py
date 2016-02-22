import os
from unittest import TestCase
from execution.QueueExecution import runThreads
from src.main.python.component.Step import *
from src.rootPath import TEST_RESOURCES
from util.NOETLJsonParser import NOETLJsonParser
from Queue import *


class TestRunThreads(TestCase):
    def test_runThreads(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        queue = Queue()
        queue.put("0")
        queue.put("1")
        queue.put("2")
        self.assertEquals(0, runThreads(config, step, queue))

    def test_runThreads_emptyQueue(self):
        filePath = os.path.join(TEST_RESOURCES, "confRunThreadsTest.json")
        config = NOETLJsonParser(filePath).getConfig()
        task = Task("task1", config)
        step = Step(task, "step1", config)
        runThreads(config, step, Queue())
