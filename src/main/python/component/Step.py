from Task import *


class Step:
    def __init__(self, task, stepName):
        self.task = task
        self.branch = None
        self.stepName = stepName
        self.stepPath = Step.getStepPath(self.task.taskName, stepName)

        stepDict = processConfRequest(task.config, self.stepPath)
        self.stepDesc = stepDict["DESC"]

        nextDict = stepDict["NEXT"]
        self.success = nextDict["SUCCESS"]
        failDict = nextDict["FAILURE"]

        self.nextFail = failDict["NEXT_STEP"]
        self.maxFailures = int(failDict["MAX_FAILURES"])
        self.waittime = getWaitTime(failDict["WAITTIME"])

        self.failures = 0
        self.cursorFail = []

        callDict = stepDict["CALL"]
        self.action = callDict["ACTION"]
        self.thread = callDict["THREAD"]

        cursor = callDict["CURSOR"]
        self.cursorRange = cursor["RANGE"]
        self.cursorDataType = cursor["DATATYPE"]
        self.cursorIncrement = cursor["INCREMENT"]
        self.cursorFormat = cursor["FORMAT"]
        self.cursor = getCursor(self.cursorRange, self.cursorDataType, self.cursorIncrement,
                                self.cursorFormat)  # immutable once initialized

        self.cursorListIndex = range(0, len(self.cursorRange))
        self.curInherit = cursor["INHERIT"]

        self.callExec = callDict["EXEC"]
        self.execLists = self.callExec["CMD"]

    @staticmethod
    def getStepPath(taskName, stepName):
        return "{0}.STEPS.{1}".format(Task.getTaskPath(taskName), stepName)
