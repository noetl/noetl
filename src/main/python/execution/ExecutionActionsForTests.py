class SupportedTestActions:
    @staticmethod
    def doTestJob(stepObj, currentCursor, testMode):
        print("Executing...")
        print(stepObj.task.taskName)
        print(stepObj.stepName)
        print("**** I am the cursor: {0} ****".format(currentCursor))
        print("Done")
        if testMode:
            stepObj.successfulCursors.append(currentCursor)
        else:
            stepObj.successfulCursors.append(currentCursor + "Done")
        return 0
