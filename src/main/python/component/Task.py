from src.main.python.util.Tools import *


class Task:
    def __init__(self, taskName, config):
        self.taskName = taskName
        self.config = config
        self.taskPath = Task.getTaskPath(self.taskName)
        taskDict = processConfRequest(config, self.taskPath)

        self.taskDesc = taskDict["DESC"]
        self.start = taskDict["START"]
        self.steps = taskDict["STEPS"]

        nextDict = taskDict["NEXT"]
        self.nextSuccess = nextDict["SUCCESS"]
        self.nextFail = nextDict["FAILURE"]

        self.stepObs = {}  # step name -> step obj, for this task
        self.branchesDict = {}  # branch name -> branch obj, for this task
        self.branchMakeComplete = {}
        # self.branchMakeComplete tells whether the branch construction completes or not
        # branch name -> boolean (false when initialized), for branches in this task
        # will be set to true once the branch construction completes.
        self.links = {}
        # self.links the recovery step name to the RECOVERABLE step name who leads to the recovery step
        # the purpose of this field is to link all failed steps and add them all to self.failedStepNames
        self.failedStepNames = []  # list of failed step names; starting point for re-run

    @staticmethod
    def getTaskPath(taskName):
        return "WORKFLOW.TASKS.{0}".format(str(taskName))

    def linkFailureHandling(self, recoverStepName, recoverableStepName):
        # recovery step is the handling step, recoverable step is the failed step
        traceLinks = self.links.get(recoverStepName)
        if traceLinks is None or len(traceLinks) == 0:
            self.links[recoverStepName] = [recoverableStepName]
        else:
            traceLinks.append(recoverableStepName)
