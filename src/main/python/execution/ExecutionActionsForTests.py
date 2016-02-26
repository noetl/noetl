import datetime
import os
import random
import time

from src.rootPath import TEST_RESOURCES
from util.CommonPrinter import printErr


class SupportedTestActions:
    def __init__(self):
        pass

    @staticmethod
    def doTestJob_ExpandedStep(stepObj, currentCursor, testMode):
        try:
            print("Executing {0}-{1} cursor {2}"
                  .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
            time.sleep(0.5)
            print("**** I am the cursor: {0} ****".format(currentCursor))
            print("Complete {0}-{1} cursor {2}"
                  .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
            if testMode:
                stepObj.successfulCursors.append(currentCursor)
            else:
                stepObj.successfulCursors.append(currentCursor + "Done")
            return 0
        except:
            printErr("doTestJob_MimicReality failed.")
            return 1

    @staticmethod
    def doTestJob_MimicReality(stepObj, currentCursor, testMode):
        try:
            print("Executing {0}-{1} cursor {2}"
                  .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
            time.sleep(5.0 * random.random())
            print("**** I am the cursor: {0} ****".format(currentCursor))
            print("Complete {0}-{1} cursor {2}"
                  .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
            if testMode:
                stepObj.successfulCursors.append(currentCursor)
            else:
                stepObj.successfulCursors.append(currentCursor + "Done")
            if random.random() < 0.5:
                raise RuntimeError("This thread work failed.")
            return 0
        except:
            printErr("doTestJob_MimicReality failed.")
            return 1

    @staticmethod
    def doTestJob_CreateFile_ForOrderTracking(stepObj, currentCursor, testMode):
        try:
            filePath = os.path.join(TEST_RESOURCES, "ChenTestGeneratedFile")
            print(filePath)
            with open(filePath, 'aw') as f:
                f.write("{0} at {1}.{2}"
                        .format(SupportedTestActionsUtils.getPrefixString(stepObj.stepName, currentCursor),
                                datetime.datetime.now(),
                                os.linesep))
            if int(currentCursor) <= 0:
                return 1
            else:
                return 0
        except:
            printErr("doTestJob_CreateFile_ForOrderTracking failed.")
            return 1


class SupportedTestActionsUtils:
    def __init__(self):
        pass

    @staticmethod
    def getPrefixString(stepName, currentCursor):
        return "Step '{0}' with cursor '{1}':::::".format(stepName, currentCursor)
