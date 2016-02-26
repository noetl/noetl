from component.Step import Step


class Branch:  # branch is a sequential presentation of steps.
    # TODO: a merge branch could be a sub class of Branch
    def __init__(self, startStepObj, mergeStepName):
        self.task = startStepObj.task
        stepName = startStepObj.stepName
        self.branchName = startStepObj.stepName  # branchName is its first step name
        self.currentStepName = startStepObj.stepName  # current Step name
        self.mergeStep = mergeStepName  # 0 if branch is not a merge branch, and dependencies should be empty
        self.lastStepName = None  # last step name, it could be the step immediately before "exit"
        self.steps = {}  # step name -> step obj, for this branch
        self.dependencies = []  # list of dependent branch names if it's a merge branch
        self.done = False  # branch successfully completed
        self.traceBranch = False  # if branch needs to be tracked in the case of a failure
        self.failedSteps = []
        self.lastFail = None  # last failed step name

        self.addStep(startStepObj)
        self.task.branchesDict[stepName] = self  # add branch to task
        self.task.branchMakeComplete[stepName] = False

    def addStep(self, stepObj):
        stepObj.branch = self
        self.steps[stepObj.stepName] = stepObj
        self.task.stepObs[stepObj.stepName] = stepObj

    def setLastStep(self, lastStep):
        self.task.branchMakeComplete[self.branchName] = True
        self.lastStepName = lastStep.stepName

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

    def isLastStep(self):
        return self.currentStepName == self.lastStepName

    def moveToNextSuccess(self):
        nextStepName = self.steps[self.currentStepName].success.values()[0][0]
        # This is safe because branch is a sequential presentation of steps
        self.currentStepName = nextStepName
        return nextStepName

    # def moveToNextFailure(self):
    #     nextStepName = self.steps[self.currentStepName].step.nextFail
    #     self.currentStepName = nextStepName
    #     return nextStepName

    def containsStep(self, stepName):
        return stepName in self.steps.keys()

    def failAtStep(self, step):
        self.traceBranch = True
        failedStepName = step.stepName
        self.failedSteps.append(failedStepName)
        self.lastFail = failedStepName
        recoverStep = Step(self.task, step.nextFail)
        self.currentStepName = recoverStep.stepName
        self.task.linkRetry(recoverStep.stepName, failedStepName)
        # add all downstream recovery steps to this branch until it reaches exit or merges with original branch
        while not self.containsStep(recoverStep.stepName) and recoverStep.stepName != "exit":
            if recoverStep.curInherit:
                recoverStep.cursor = step.cursor
            # TODO: This might be a problem if recoverStep points to a step in downstream branch that is in the same task.
            self.addStep(recoverStep)
            # TODO: This assumes that recovery part is a sequence of steps. It is true for the immediately next step, but not necessarily true after that.
            recoverStep = Step(self.task, recoverStep.success.values()[0][0])
