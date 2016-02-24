from src.main.python.util.Tools import *


class Task:
    def __init__(self, taskName, config):
        self.taskName = taskName
        self.taskPath = Task.getTaskPath(self.taskName)
        taskDict = processConfRequest(config, self.taskPath)

        self.taskDesc = taskDict["DESC"]
        self.start = taskDict["START"]
        self.steps = taskDict["STEPS"]

        nextDict = taskDict["NEXT"]
        self.nextTask = nextDict["SUCCESS"]
        self.nextFail = nextDict["FAILURE"]

        self.stepObs = {}  # step name -> step obj, for this task
        self.branchesDict = {}  # branch name -> branch obj, for this task
        self.branchMakeComplete = {}
        # this dictionary tells whether a branch construction completes or not
        # branch name -> boolean (false when initialized), for branches in this task
        # will be set to true once the branch construction completes.
        self.links = {}  # links the recovery step name to the RECOVERABLE step name who leads to the recovery step
        self.restart = []  # list of failed step names; starting point for re-run

    @staticmethod
    def getTaskPath(taskName):
        return "WORKFLOW.TASKS.{0}".format(str(taskName))

    def linkRetry(self, recoverStepName, recoverableStepName):
        traceLinks = self.links.get(recoverStepName)
        if len(traceLinks) == 0:
            self.links[recoverStepName] = [recoverableStepName]
        else:
            traceLinks.append(recoverableStepName)
