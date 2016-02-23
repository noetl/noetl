class Branch:
    # TODO: a merge branch could be a sub class of Branch
    def __init__(self, startStepObj, mergeStepName):
        self.task = startStepObj.task
        stepName = startStepObj.stepName
        self.branchName = stepName  # branchName is its first step name
        self.curStep = stepName  # current Step name
        self.mergeStep = mergeStepName  # 0 if branch is not a merge branch, and dependencies should be empty
        self.lastStep = None
        self.steps = {}  # step name -> step obj, for this branch
        self.dependencies = []  # list of dependent branch names if it's a merge branch
        self.done = False  # branch successfully completed
        self.traceBranch = False  # if branch needs to be tracked in the case of a failure
        self.failedSteps = []
        self.lastFail = None

        self.steps[stepName] = startStepObj  # add step to branch
        self.task.stepObs[stepName] = startStepObj  # add step to task
        self.task.branchesDict[stepName] = self  # add branch to task
        self.task.branchValidDict[stepName] = False
