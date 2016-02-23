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

        self.stepObs = {}                       # step name -> step obj, for this task
        self.branchesDict = {}                  # branch name -> branch obj, for this task
        self.branchValidDict = {}               # branch name -> boolean (false when initialized), for this task
                                                # this serves task validation purposes;
        self.links = {}
        self.restart = []  # list of failed step names; starting point for re-run

    @staticmethod
    def getTaskPath(taskName):
        return "WORKFLOW.TASKS.{0}".format(str(taskName))
