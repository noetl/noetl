class Branch:  # branch is a sequential presentation of steps.
    # TODO: a merge branch could be a sub class of Branch
    def __init__(self, startStepObj, mergeStepName):
        self.task = startStepObj.task
        stepName = startStepObj.stepName
        self.branchName = stepName  # branchName is its first step name
        self.curStep = stepName  # current Step name
        self.mergeStep = mergeStepName  # 0 if branch is not a merge branch, and dependencies should be empty
        self.lastStep = None  # last step name
        self.steps = {}  # step name -> step obj, for this branch
        self.dependencies = []  # list of dependent branch names if it's a merge branch
        self.done = False  # branch successfully completed
        self.traceBranch = False  # if branch needs to be tracked in the case of a failure
        self.failedSteps = []
        self.lastFail = None

        self.steps[stepName] = startStepObj  # add step to branch
        self.task.stepObs[stepName] = startStepObj  # add step to task
        self.task.branchesDict[stepName] = self  # add branch to task
        self.task.branchMakeComplete[stepName] = False

    def addStep(self, stepObj):
        self.steps[stepObj.stepName] = stepObj
        self.task.stepObs[stepObj.stepName] = stepObj

    def setLastStep(self, lastStepName):
        self.task.branchMakeComplete[self.branchName] = True
        self.lastStep = lastStepName

    # We don't want to make mergeBranch (multiple times) if not all dependencies are complete
    def dependenciesMakeComplete(self):
        for b in self.dependencies:
            if not self.task.branchMakeComplete[b]:
                return False
        return True

    # We don't want to run mergeBranch (multiple times) if not all dependencies are complete
    def dependenciesExecutionComplete(self):
        for b in self.dependencies:
            if not self.task.branchesDict[b].done:
                return False
        return True

    def atLastStep(self):
        return self.curStep == self.lastStep

    def moveToNextStep(self):
        nextStepName = self.steps[self.curStep].success.values()[0][0]
        # This is safe because branch is a sequential presentation of steps
        self.curStep = nextStepName
