from src.main.python.util.Tools import *


class Step:
    def __init__(self, taskParent, stepName, config):
        self.task = taskParent
        self.stepName = stepName
        self.stepPath = "{0}.STEPS.{1}".format(self.task.taskPath, self.stepName)

        self.stepDesc = processConfRequest(config, self.stepPath + ".DESC")
        self.success = processConfRequest(config, self.stepPath + ".NEXT.SUCCESS")
        self.nextFail = processConfRequest(config, self.stepPath + ".NEXT.FAILURE.NEXT_STEP")
        self.maxFailures = int(processConfRequest(config, self.stepPath + ".NEXT.FAILURE.MAX_FAILURES"))
        self.waittime = getWaitTime(processConfRequest(config, self.stepPath + ".NEXT.FAILURE.WAITTIME"))
        self.action = processConfRequest(config, self.stepPath + ".CALL.ACTION")
        self.failures = 0
        self.cursorFail = []
        self.thread = processConfRequest(config, self.stepPath + ".CALL.THREAD")
        self.cursor = getCursor(
            processConfRequest(config, self.stepPath + ".CALL.CURSOR.RANGE"),
            processConfRequest(config, self.stepPath + ".CALL.CURSOR.DATATYPE"),
            processConfRequest(config, self.stepPath + ".CALL.CURSOR.INCREMENT"),
            processConfRequest(config, self.stepPath + ".CALL.CURSOR.FORMAT"))
        self.cursorListIndex = processConfRequest(config, self.stepPath + ".CALL.CURSOR.RANGE", True)
        self.curInherit = processConfRequest(config, self.stepPath + ".CALL.CURSOR.INHERIT")
