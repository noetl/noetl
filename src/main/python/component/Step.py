from Task import *


class Step:
    def __init__(self, taskParent, stepName, config):
        self.task = taskParent
        self.stepName = stepName
        self.stepPath = Step.getStepPath(self.task.taskName, stepName)

        self.stepDesc = processConfRequest(config, self.stepPath + ".DESC")
        self.success = processConfRequest(config, self.stepPath + ".NEXT.SUCCESS")
        self.nextFail = processConfRequest(config, self.stepPath + ".NEXT.FAILURE.NEXT_STEP")
        self.maxFailures = int(processConfRequest(config, self.stepPath + ".NEXT.FAILURE.MAX_FAILURES"))
        self.waittime = getWaitTime(processConfRequest(config, self.stepPath + ".NEXT.FAILURE.WAITTIME"))
        self.action = processConfRequest(config, self.stepPath + ".CALL.ACTION")
        self.failures = 0
        self.cursorFail = []
        self.thread = processConfRequest(config, self.stepPath + ".CALL.THREAD")

        self.cursorRange = processConfRequest(config, self.stepPath + ".CALL.CURSOR.RANGE")
        self.cursorDataType = processConfRequest(config, self.stepPath + ".CALL.CURSOR.DATATYPE")
        self.cursorIncrement = processConfRequest(config, self.stepPath + ".CALL.CURSOR.INCREMENT")
        self.cursorFormat = processConfRequest(config, self.stepPath + ".CALL.CURSOR.FORMAT")
        self.cursor = getCursor(self.cursorRange, self.cursorDataType, self.cursorIncrement, self.cursorFormat)
        self.cursorListIndex = processConfRequest(config, self.stepPath + ".CALL.CURSOR.RANGE", True)
        self.curInherit = processConfRequest(config, self.stepPath + ".CALL.CURSOR.INHERIT")

        self.execLists = processConfRequest(config, self.stepPath + ".CALL.EXEC.CMD")

    @staticmethod
    def getStepPath(taskName, stepName):
        return "{0}.STEPS.{1}".format(Task.getTaskPath(taskName), stepName)
