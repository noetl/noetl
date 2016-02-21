class Branch:
    def __init__(self, taskParent, curStepName, mergeStepName):
        self.task = taskParent
        self.branchName = curStepName  # branchName = first step in  branch
        self.curStep = curStepName  # curStep name
        self.mergeStep = mergeStepName  # 0 if branch not the product of a fork
        self.lastStep = None
        self.steps = {}  # map of step names to steps in branch
        self.dependencies = []  # list of branch names
        self.done = False  # branch successfully completed
        self.traceBranch = False  # if branch needs to be tracked in the case of a failure
        self.failedSteps = []
        self.lastFail = None
