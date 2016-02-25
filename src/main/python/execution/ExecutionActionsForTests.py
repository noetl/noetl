import time


class SupportedTestActions:
    @staticmethod
    def doTestJob(stepObj, currentCursor, testMode):
        print(
            "Executing {0}-{1} cursor {2}"
                .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
        time.sleep(2)
        print("**** I am the cursor: {0} ****".format(currentCursor))
        print(
            "Complete {0}-{1} cursor {2}"
                .format(str(stepObj.task.taskName), str(stepObj.stepName), str(currentCursor)))
        if testMode:
            stepObj.successfulCursors.append(currentCursor)
        else:
            stepObj.successfulCursors.append(currentCursor + "Done")
        return 0
