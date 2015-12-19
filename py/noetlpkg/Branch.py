class Branch:
    def __init__(self, task, curStep, mergeStep):
        self.task = task
        self.branchName = curStep # branchName = first step in  branch
        self.curStep = curStep # curStep name
        self.mergeStep  = mergeStep # 0 if branch not the product of a fork
        self.lastStep = None
        self.steps = {} # map of step names to steps in branch
        self.dependencies = [] # list of branch names
        self.done = False # branch successfully completed
        self.traceBranch = False # if branch needs to be tracked in the case of a failure
        self.failedSteps = []
        self.lastFail = None