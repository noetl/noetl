from noetl.noetl import config, getWaittime, getCursor
from noetl.noetlpkg.EvalJsonParser import getConfig


class Step:
    def __init__(self, task, stepName):
        self.task = task
        self.stepName = stepName
        self.stepDesc = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".DESC")
        self.success = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.SUCCESS")
        self.nextFail = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.FAILURE.NEXT_STEP")
        self.maxFailures = int(getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.FAILURE.MAX_FAILURES"))
        self.waittime = getWaittime(getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.FAILURE.WAITTIME"))
        self.action = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.ACTION")
        self.failures = 0
        self.cursorFail = []

        self.thread = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.THREAD")
        self.cursor = getCursor(getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.RANGE"), \
                                getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.DATATYPE"), \
                                getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.INCREMENT"), \
                                getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.FORMAT"))
        self.cursorListIndex = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.RANGE", "LIST_INDEX")
        self.curInherit = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.INHERIT")