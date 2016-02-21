from src.main.python.util.Tools import *


class Step:
    def __init__(self, taskParent, stepName, config):
        self.task = taskParent
        self.stepName = stepName
        stepPath = Step.__stepPath(stepName, taskParent)

        self.stepDesc = processConfRequest(config, stepPath + ".DESC")
        self.success = processConfRequest(config, stepPath + ".NEXT.SUCCESS")
        self.nextFail = processConfRequest(config, stepPath + ".NEXT.FAILURE.NEXT_STEP")
        self.maxFailures = int(processConfRequest(config, stepPath + ".NEXT.FAILURE.MAX_FAILURES"))
        self.waittime = getWaitTime(processConfRequest(config, stepPath + ".NEXT.FAILURE.WAITTIME"))
        self.action = processConfRequest(config, stepPath + ".CALL.ACTION")
        self.failures = 0
        self.cursorFail = []
        self.thread = processConfRequest(config, stepPath + ".CALL.THREAD")
        self.cursor = getCursor(
            processConfRequest(config, stepPath + ".CALL.CURSOR.RANGE"),
            processConfRequest(config, stepPath + ".CALL.CURSOR.DATATYPE"),
            processConfRequest(config, stepPath + ".CALL.CURSOR.INCREMENT"),
            processConfRequest(config, stepPath + ".CALL.CURSOR.FORMAT"))
        self.cursorListIndex = processConfRequest(config, stepPath + ".CALL.CURSOR.RANGE", True)
        self.curInherit = processConfRequest(config, stepPath + ".CALL.CURSOR.INHERIT")

    @staticmethod
    def __stepPath(name, parent):
        return "WORKFLOW.TASKS." + str(parent.taskName) + ".STEPS." + str(name)
