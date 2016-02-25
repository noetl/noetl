import time
from Queue import Queue
from threading import Thread

from src.main.python.component.Branch import Branch
from src.main.python.component.Step import Step
from src.main.python.component.Task import Task
from src.main.python.execution.QueueExecution import runThreads
from src.main.python.util import Tools
from src.main.python.util.CommonPrinter import *
from src.main.python.util.NOETLJsonParser import NOETLJsonParser
from src.main.python.util.Tools import processConfRequest

FIRST_TASK_NAME = "start"
LAST_TASK_NAME = "exit"

testMode = False


def main(argv=None):
    global testMode
    if len(argv) != 2:
        raise RuntimeError("Expecting a configuration file path as its argument.")

    configFilePath = str(argv[1])
    printInfo('Using configuration file "{0}"'.format(configFilePath))
    config = NOETLJsonParser(configFilePath).getConfig()
    try:
        testMode = True if processConfRequest(config, "WORKFLOW.TEST.FLAG") == "True" else False
        if testMode:
            return doTest(config)
        else:
            task = Task(FIRST_TASK_NAME, config)
            exitCode = getTask(config, task)
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
        exitCode = getTask(config, task)
        printInfo("Finished test mode with exit code {0}".format(exitCode))
        return exitCode
    except:
        printErr("Test mode failed.")
        return 1


def getTask(config, taskObj):
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
            exitCode = runTask(taskObj, config)
            if exitCode == 1 or len(taskObj.restart) >= 0:
                printInfo("Task '{0}' failed. Restart step(s) is(are) '{1}'."
                          .format(taskObj.taskName, ",".join(taskObj.restart)))
                for restartStepName in taskObj.restart:
                    printInfo('Step "{0}" failed with cursors "{1}".'.format(restartStepName, str(
                        taskObj.stepObs[restartStepName].cursorFail)))
                return getTask(config, Task(taskObj.nextFail, config))
            else:
                return getTask(config, Task(taskObj.nextTask, config))
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
                if mergeBranch.dependenciesMakeComplete():
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


def runTask(taskObj, config):
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
            exitCode = forkBranches(taskObj, branchQueue, config)
        elif len(startBranchNames) == 1:
            branchName = startBranchNames[0]
            branch = taskObj.branchesDict[branchName]
            exitCode = runBranch(taskObj, branch, config)
        else:
            raise RuntimeError("No starting steps found for the task '{0}'".format(taskObj.taskName))
    except:
        printErr("Exception occurred in runTask for task '{0}'.".format(taskObj.taskName))
        return 1
    printInfo("Execution time for task '{0}' is: {1}."
              .format(taskObj.taskName, datetime.datetime.now() - taskStartDate))
    return exitCode


def forkBranches(taskObj, branchQueue, config):
    try:
        for branchId in range(branchQueue.qsize()):
            branch = Thread(target=runBranchQueue, args=(taskObj, branchQueue, config,))
            branch.setDaemon(True)
            branch.start()
        branchQueue.join()
        return 0
    except:
        printErr("forkBranches execution failed.")
        return 1


def runBranchQueue(taskObj, branchQueue, config):
    if branchQueue.empty():
        printInfo("runBranchQueue - branchQueue is empty")
        return 1
    branch = None
    try:
        branch = branchQueue.get()
        printInfo("Running branchQueue branch: " + branch.branchName)
        exitCode = runBranch(taskObj, branch, config)
        branchQueue.task_done()
        return exitCode
    except:
        printErr("branchQueue failed for branch: " + branch.branchName)
        return 1


def runBranch(taskObj, branchObj, config):
    try:  # execute current step for branch
        currentStep = branchObj.steps[branchObj.curStep]
        printInfo(
            "Run branch at step '{0}' with failed cursor '{1}'.".format(currentStep.stepPath, currentStep.cursorFail))
        currentStep.cursorFail = []  # reset before running again
        exitCode = runStep(taskObj, currentStep, branchObj, config)

        if exitCode == 0:
            if not branchObj.atLastStep():
                branchObj.moveToNextStep()
                if branchObj.traceBranch:
                    if branchObj.curStep == branchObj.lastFail:  # remove nextFail loop from links
                        def removeLink(stepName):
                            delNext = taskObj.links.get(stepName)
                            if delNext is not None:
                                del taskObj.links[stepName]
                                for delN in delNext:
                                    removeLink(delN)

                        removeLink(currentStep.stepName)
                        branchObj.traceBranch = False
                    else:
                        taskObj.linkRetry(branchObj.curStep, currentStep.stepName)
                return runBranch(taskObj, branchObj, config)
            else:  # At branch last step. Start new branch.
                branchObj.done = True
                nextStepName = currentStep.success.values()[0][0]
                if len(currentStep.success.values()) == 1 and len(currentStep.success.values()[0]) == 1:
                    if nextStepName == "exit":
                        return 0
                    nextBranch = taskObj.branchesDict[nextStepName]
                    if branchObj.traceBranch:
                        nextBranch.traceBranch = True
                        taskObj.linkRetry(nextStepName, currentStep.stepName)
                    if nextBranch.dependenciesExecutionComplete():
                        return runBranch(taskObj, nextBranch, config)
                elif len(currentStep.success.values()) > 1 or len(currentStep.success.values()[0]) > 1:
                    branchQueue = Queue()
                    for mergeStep, branchList in currentStep.success.iteritems():
                        for forkBranchName in branchList:
                            forkBranchName = taskObj.branchesDict[forkBranchName]
                            if branchObj.traceBranch:  # trace forked branches
                                forkBranchName.traceBranch = True
                                taskObj.linkRetry(forkBranchName, currentStep.stepName)
                            branchQueue.put(forkBranchName)
                    # Chen: There is potential bug here.
                    # Consider this case: task.start:{m1:[s1,s2]}. steps{s1.next.success{0:[m1,m2]}}
                    # This code will run step m1 without checking the status of s2.
                    # If s2 is not ready, m1 should not start. Add dependencies checks here.
                    return forkBranches(taskObj, branchQueue, config)
                else:
                    raise RuntimeError("Step '{0}' has empty or unsupported success configurations '{1}'."
                                       .format(currentStep.stepName, currentStep.success))
        else:  # when step failed
            # step has failed before (broken link) - traceback
            if currentStep.stepName in branchObj.failedSteps or currentStep.nextFail == "exit":
                def traceback(stepName):
                    if stepName in taskObj.links.keys():
                        for name in taskObj.links[stepName]:
                            traceback(name)
                    elif stepName not in taskObj.restart:
                        # Add recoverable steps to restart list. This will be used for the task restart.
                        taskObj.restart.append(stepName)

                traceback(currentStep.stepName)
                return 1  # exitCode = 1
            else:  # fail for the first time and try to recover
                recoverStep = Step(taskObj, currentStep.nextFail, config)
                branchObj.traceBranch = True
                branchObj.failedSteps.append(currentStep.stepName)
                branchObj.lastFail = currentStep.stepName
                branchObj.curStep = recoverStep.stepName
                taskObj.linkRetry(recoverStep.stepName, currentStep.stepName)
                while recoverStep.stepName != "exit" and recoverStep.stepName not in branchObj.steps.keys() and \
                        (recoverStep.stepName != branchObj.lastStep):
                    # add nextFail steps to step list until failBranch merges with original branch or ends
                    if recoverStep.curInherit:
                        recoverStep.cursor = currentStep.cursor
                    branchObj.addStep(recoverStep)
                    # TODO: this assume that failure branch can only be a sequence of steps
                    recoverStep = Step(taskObj, recoverStep.success.values()[0][0], config)
                if recoverStep.stepName == "exit":
                    branchObj.lastStep = "exit"
                return runBranch(taskObj, branchObj, config)
    except:
        currentStep = branchObj.steps[branchObj.curStep]
        printErr("Failed to get current step '{0}' with path '{1}'.".format(currentStep.stepName, currentStep.stepPath))
        return 1


def runStep(task, step, branch, config):
    try:
        exitCode, stepStartDate = 0, datetime.datetime.now()
        printInfo("RunStep for step '{0}' with cursors '{1}' using '{2}' thread(s)."
                  .format(step.stepName, step.cursor, step.thread))
        cursorQueue = Queue()
        for cur in step.cursor:
            cursorQueue.put(cur)
        runThreads(config, step, cursorQueue, testMode)
        printInfo(
            "Execution time for step '{0}' is: '{1}'.".format(step.stepName, datetime.datetime.now() - stepStartDate))

        if len(step.cursorFail) != 0:
            printInfo("Step '{0}' failed with these cursors '{1}'.".format(step.stepPath, step.cursorFail))
            step.cursor = step.cursorFail
            step.failures += 1
            if step.failures < step.maxFailures:
                step.cursorFail = []
                time.sleep(step.waittime)
                return runStep(task, step, branch, config)
            else:
                printInfo("Run step '{0}' failed for '{1}' times reaching the step.maxFailures '{2}'."
                          .format(step.stepPath, step.failures, step.maxFailures))
                return 1
        return 0
    except:
        printErr("RunStep failed for step '{0}'.".format(step.stepName))
        return 1


if __name__ == "__main__":
    sys.exit(main())
