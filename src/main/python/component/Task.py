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

        self.branchesDict = {}  # maps of branchName to branch object
        self.branchValidDict = {}  # for task validating purposes; map branch name to boolean
        self.links = {}
        self.restart = []  # list of failed steps; starting point for re-run
        self.stepObs = {}  # maps stepname to step object

    @staticmethod
    def getTaskPath(taskName):
        return "WORKFLOW.TASKS.{0}".format(str(taskName))
