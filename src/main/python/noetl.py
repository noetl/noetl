from Queue import Queue

from component.Branch import Branch
from component.Step import Step
from component.Task import Task
from src.main.python.util.CommonPrinter import *
from util import Tools
from util.NOETLJsonParser import NOETLJsonParser
from util.Tools import processConfRequest

FIRST_TASK_NAME = "start"
LAST_TASK_NAME = "exit"


def main(argv=None):
    if len(argv) != 2:
        raise RuntimeError("Expecting a configuration file path as its argument.")

    configFilePath = str(argv[1])
    printInfo('Using configuration file "{0}"'.format(configFilePath))
    config = NOETLJsonParser(configFilePath).getConfig()
    testMode = True if processConfRequest(config, "WORKFLOW.TEST.FLAG") == "True" else False
    try:
        if testMode:
            return doTest(config)
        else:
            task = Task(FIRST_TASK_NAME, config)
            exitCode = getTask(config, task, False)
            return exitCode
    except:
        printErr("NOETL Failed.")
        return 1


def doTest(config):
    try:
        printInfo("In test mode...")
        logName = processConfRequest(config, "LOGGING.0.NAME")
        printInfo('Log file is "{0}"'.format(logName))

        taskList = processConfRequest(config, "WORKFLOW.TASKS")
        printInfo("LIST of TASKS:\n" + taskList)

        task = Task(FIRST_TASK_NAME, config)
        exitCode = getTask(config, task, True)
        printInfo("Finished test mode with exit code {0}".format(exitCode))
        return exitCode
    except:
        printErr("Test mode failed.")
        return 1


def getTask(config, taskObj, testMode):
    if Tools.REQUEST_FAILED in taskObj.taskName:
        return 1
    try:
        printInfo("Getting task '{0}' with description '{1}'. Next task is '{2}'"
                  .format(taskObj.taskName, taskObj.taskDesc, taskObj.nextTask))
        # Make branches for the task before execution.
        startDictValues = taskObj.start.values()
        if len(startDictValues) == 1 and len(startDictValues[0]) == 1:  # only 1 item in the dict, and have only 1 step.
            stepObj = Step(taskObj, startDictValues[0][0], config)
            if taskObj.start.keys()[0] != "0":
                raise RuntimeError("You cannot define merge step when there is only one start step. "
                                   "Alternatively, you can move the merge step to the step's next.success")
            branch = Branch(stepObj, "0")
            makeBranches(taskObj, branch, stepObj, config)
        elif len(startDictValues) > 1 or len(startDictValues[0]) > 1:  # forking branches
            makeBranchesForForkingStep(taskObj.start, config)
        else:
            # TODO: There are many cases we didn't cover, such as
            # start:{0:[]}, start:{0:[1,2]}, start:{1:[]}, start:{2:[], 2:[1]}
            # In reality, we are check the length of combined list of startDictValues
            raise RuntimeError("Task '{0}' has empty or unsupported start steps '{1}'."
                               .format(taskObj.taskName, taskObj.start))
        # start task execution.
        if taskObj.taskName == LAST_TASK_NAME:
            return 0
        if taskObj.taskName == FIRST_TASK_NAME:
            exitCode = runTask(taskObj)
            if exitCode == 1 or len(taskObj.restart) >= 0:
                printInfo("Task '{0}' failed. Restart step(s) is(are) '{1}'."
                          .format(taskObj.taskName, ",".join(taskObj.restart)))
                for restartStepName in taskObj.restart:
                    printInfo('Step "{0}" failed with cursors "{1}".'.format(restartStepName, str(
                        taskObj.stepObs[restartStepName].cursorFail)))
                return getTask(config, Task(taskObj.nextFail, config), testMode)
            else:
                return getTask(config, Task(taskObj.nextTask, config), testMode)
    except:
        printErr("getTask failed for task '{0}'".format(str(taskObj)))
        return 1


def makeBranches(taskObj, branchObj, stepObj, config):
    try:
        stepSuccessValues = stepObj.success.values()
        if len(stepSuccessValues) == 1 and len(stepSuccessValues[0]) == 1:  # sequential steps.
            nextStepName = stepSuccessValues[0][0]
            nextStep = Step(taskObj, nextStepName, config)
            if nextStepName == "exit":
                branchObj.setLastStep(stepObj.stepName)
                return 0
            if nextStepName == branchObj.mergeStep:
                branchObj.setLastStep(stepObj.stepName)
                mergeBranch = taskObj.branchesDict[nextStepName]
                if mergeBranch.dependenciesMakeComplete:
                    return makeBranches(taskObj, mergeBranch, nextStep, config)
                else:
                    return 0
            else:
                branchObj.addStep(nextStep)
                return makeBranches(taskObj, branchObj, nextStep, config)
        if len(stepSuccessValues) > 1 or len(stepSuccessValues[0]) > 1:  # create new branches if forking
            branchObj.setLastStep(stepObj.stepName)
            makeBranchesForForkingStep(stepObj, config)
        raise RuntimeError("Unsupported NEXT.SUCCESS configuration for the step '{0}': {1}"
                           .format(stepObj.stepName, stepObj.success))
    except:
        printErr("MakeBranches failed for task:  ", taskObj.taskName, stepObj.stepName)
        return 1


def makeBranchesForForkingStep(forkingStepObj, config):  # make sure step is a forking one before you call it.
    exitCode = 0
    taskObj = forkingStepObj.task
    for mergeStepName, branchNames in forkingStepObj.iteritems():
        if mergeStepName != "0":  # If 0, branches don't merge.
            # Otherwise, create merge branch and add forked branches as its dependency
            mergeStep = Step(taskObj, mergeStepName, config)
            mergeBranch = Branch(mergeStep, "0")
            for branchName in branchNames:
                mergeBranch.dependencies.append(branchName)
                # makeBranches for mergeBranch happens somewhere in makeBranches
        for branchName in branchNames:
            stepObj = Step(taskObj, branchName, config)
            newBranch = Branch(stepObj, mergeStepName)
            exitCode += makeBranches(taskObj, newBranch, stepObj, config)
    return min(1, exitCode)


def runTask(taskObj):
    try:
        printInfo("Running task '{0}' with starting steps '{1}'.".format(taskObj.taskName, taskObj.start))
        exitCode, taskStartDate = 0, datetime.datetime.now()

        startBranchNames = []
        for mergeStepName, branchNames in taskObj.start.iteritems():
            startBranchNames += branchNames
        if len(startBranchNames) > 1:
            branchQueue = Queue()
            for branchName in startBranchNames:
                branchQueue.put(taskObj.branchesDict[branchName])
            exitCode = forkBranches(taskObj, branchQueue)
        elif len(startBranchNames) == 1:
            branchName = startBranchNames[0]
            branch = taskObj.branchesDict[branchName]
            exitCode = getStep(taskObj, branch)
        else:
            raise RuntimeError("No starting steps found for the task '{0}'".format(taskObj.taskName))
    except:
        printErr("Exception occurred in runTask for task '{0}'.".format(taskObj.taskName))
        return 1
    printInfo("Execution time for task '{0}' is: {1}."
              .format(taskObj.taskName, datetime.datetime.now() - taskStartDate))
    return exitCode


def forkBranches(task, branchQueue):
    return 0


def getStep(task, branch):
    return 0


if __name__ == "__main__":
    sys.exit(main())
