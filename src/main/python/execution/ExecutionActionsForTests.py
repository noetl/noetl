import random
import time


class SupportedTestActions:
    @staticmethod
    def doTestJob_ExpandedStep(stepObj, currentCursor, testMode):
        print(
            "Executing {0}-{1} cursor {2}"
                .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
        time.sleep(0.5)
        print("**** I am the cursor: {0} ****".format(currentCursor))
        print(
            "Complete {0}-{1} cursor {2}"
                .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
        if testMode:
            stepObj.successfulCursors.append(currentCursor)
        else:
            stepObj.successfulCursors.append(currentCursor + "Done")
        return 0

    @staticmethod
    def doTestJob_MimicReality(stepObj, currentCursor, testMode):
        print(
            "Executing {0}-{1} cursor {2}"
                .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
        time.sleep(5.0 * random.random())
        print("**** I am the cursor: {0} ****".format(currentCursor))
        print(
            "Complete {0}-{1} cursor {2}"
                .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
        if testMode:
            stepObj.successfulCursors.append(currentCursor)
        else:
            stepObj.successfulCursors.append(currentCursor + "Done")
        if random.random() < 0.5:
            raise RuntimeError("this thread work failed.")
        return 0
