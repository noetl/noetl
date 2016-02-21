from src.main.python.util.Tools import *


class Step:
    def __init__(self, taskParent, stepName, config):
        self.task = taskParent
        self.stepName = stepName
        self.stepDesc = processConfRequest(config, self.__getPath(".DESC"))
        self.success = processConfRequest(config, self.__getPath(".NEXT.SUCCESS"))
        self.nextFail = processConfRequest(config, self.__getPath(".NEXT.FAILURE.NEXT_STEP"))
        self.maxFailures = int(processConfRequest(config, self.__getPath(".NEXT.FAILURE.MAX_FAILURES")))
        self.waittime = getWaitTime(processConfRequest(config, self.__getPath(".NEXT.FAILURE.WAITTIME")))
        self.action = processConfRequest(config, self.__getPath(".CALL.ACTION"))
        self.failures = 0
        self.cursorFail = []
        self.thread = processConfRequest(config, self.__getPath(".CALL.THREAD"))
        self.cursor = getCursor(
            processConfRequest(config, self.__getPath(".CALL.CURSOR.RANGE")),
            processConfRequest(config, self.__getPath(".CALL.CURSOR.DATATYPE")),
            processConfRequest(config, self.__getPath(".CALL.CURSOR.INCREMENT")),
            processConfRequest(config, self.__getPath(".CALL.CURSOR.FORMAT")))
        self.cursorListIndex = processConfRequest(config, self.__getPath(".CALL.CURSOR.RANGE"), True)
        self.curInherit = processConfRequest(config, self.__getPath(".CALL.CURSOR.INHERIT"))

    def __getPath(self, relativePath):
        return "WORKFLOW.TASKS.{0}.STEPS.{1}{2}" \
            .format(str(self.task.taskName), str(self.stepName), str(relativePath))
