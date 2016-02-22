from util.Tools import *


class Task:
    def __init__(self, taskName, config):
        self.taskName = taskName
        self.taskPath = Task.getTaskPath(self.taskName)
        self.taskDesc = processConfRequest(config, self.taskPath + ".DESC")
        self.start = processConfRequest(config, self.taskPath + ".START")
        self.steps = processConfRequest(config, self.taskPath + ".STEPS")
        self.nextTask = processConfRequest(config, self.taskPath + ".NEXT.SUCCESS")
        self.nextFail = processConfRequest(config, self.taskPath + ".NEXT.FAILURE")
        self.branchesDict = {}  # maps of branchName to branch object
        self.branchValidDict = {}  # for task validating purposes; map branch name to boolean
        self.links = {}
        self.restart = []  # list of failed steps; starting point for re-run
        self.stepObs = {}  # maps stepname to step object

    @staticmethod
    def getTaskPath(taskName):
        return "WORKFLOW.TASKS.{0}".format(str(taskName))
