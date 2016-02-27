import os

from noetl import main
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