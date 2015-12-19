from noetl.noetl import config
from noetl.noetlpkg.EvalJsonParser import getConfig


class Task:
    def __init__(self, taskName):
        self.taskName = taskName
        self.taskDesc = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".DESC")
        self.start = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".START")
        self.steps = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".STEPS")
        self.nextTask = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".NEXT.SUCCESS")
        self.nextFail = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".NEXT.FAILURE")
        self.branchesDict = {} # maps of branchName to branch object
        self.branchValidDict = {} # for task validating purposes; map branch name to boolean
        self.links = {}
        self.restart = [] # list of failed steps; starting point for re-run
        self.stepObs = {} # maps stepname to step object