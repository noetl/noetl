import os
from unittest import TestCase
from src.main.python.noetl import *
from src.rootPath import TEST_RESOURCES


class TestNOETL(TestCase):
    def test_goThroughMostBasic(self):
        filePath = os.path.join(TEST_RESOURCES, "noetlTest_mostBasic.json")
        main([None, filePath])
