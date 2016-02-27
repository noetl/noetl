import time
from Queue import Queue
from threading import Thread
from src.main.python.component.Branch import Branch
from src.main.python.component.Step import Step
from src.main.python.component.Task import Task
from src.main.python.execution.QueueExecution import runCursorQueue
from src.main.python.util.CommonPrinter import *
from src.main.python.util.NOETLJsonParser import NOETLJsonParser
from src.main.python.util.Tools import processConfRequest

FIRST_TASK_NAME = "start"
testMode = False


def main(argv=None):
    global testMode
    if len(argv) != 2:
        raise RuntimeError("Expecting a configuration file path as its argument.")

    try:
        configFilePath = str(argv[1])
        printInfo('Using configuration file "{0}"'.format(configFilePath))
        config = NOETLJsonParser(configFilePath).getConfig()
        testMode = True if processConfRequest(config, "WORKFLOW.TEST.FLAG") == "True" else False
        if testMode:
            return doTest(config)
        else:
            task = Task(FIRST_TASK_NAME, config)
            getTask(config, task)
    except:
        printErr("NOETL Failed.")


def doTest(config):
    try:
        printInfo("In test mode...")
        logName = processConfRequest(config, "LOGGING.0.NAME")
        printInfo('Log file is "{0}"'.format(logName))

        taskList = processConfRequest(config, "WORKFLOW.TASKS")
        printInfo("LIST of TASKS:\n" + str(taskList))

        task = Task(FIRST_TASK_NAME, config)
        getTask(config, task)
    except:
        printErr("Test mode failed.")


def getTask(config, taskObj):
    try:
        printInfo("Getting task '{0}' with description '{1}'. Next task is '{2}'"
                  .format(taskObj.taskName, taskObj.taskDesc, taskObj.nextSuccess))
        if taskObj.taskName == "exit":
            return
        # Make branches for the task before execution.
        startDictValues = taskObj.start.values()
        if len(startDictValues) == 1 and len(startDictValues[0]) == 1:  # only 1 item in the dict, and have only 1 step.
            stepObj = Step(taskObj, startDictValues[0][0])
            if taskObj.start.keys()[0] != "0":
                raise RuntimeError("You cannot define merge step when there is only one start step. "
                                   "Alternatively, you can move the merge step to the step's next.success")
            branch = Branch(stepObj, "0")
            extendBranchFromStep(branch, stepObj)
        elif len(startDictValues) > 1 or len(startDictValues[0]) > 1:  # forking branches
            makeForkBranches(taskObj, taskObj.start)
        else:
            # TODO: There are many cases we didn't cover, such as
            # start:{1:[1]}, start:{5:[1,2], 5:[3,4]}, start:{5:[1,2], 2:[5]}, start:{2:[], 2:[1]}
            # In reality, we are check the length of combined list of startDictValues
            raise RuntimeError("Task '{0}' has empty or unsupported start steps '{1}'."
                               .format(taskObj.taskName, taskObj.start))
        # start task execution.
        if taskObj.taskName == FIRST_TASK_NAME:
            taskStartDate = datetime.datetime.now()
            runTask(taskObj)
            printInfo("Execution time for task '{0}' is: {1}."
                      .format(taskObj.taskName, datetime.datetime.now() - taskStartDate))
            if len(taskObj.failedStepNames) > 0:
                printFailedInfo(taskObj)
                getTask(config, Task(taskObj.nextFail, config))
            else:
                printInfo("Task '{0}' finished successfully.".format(taskObj.taskName))
                getTask(config, Task(taskObj.nextSuccess, config))
    except:
        printErr("getTask failed for task '{0}'".format(str(taskObj)))


def printFailedInfo(taskObj):
    printInfo("FAILURE: Task '{0}' failed with step(s): '{1}'."
              .format(taskObj.taskName, ",".join(taskObj.failedStepNames)))
    for failedStep in taskObj.failedStepNames:
        printInfo('FAILURE: Step "{0}" failed with cursors "{1}".'
                  .format(failedStep, taskObj.stepObs[failedStep].cursorFail))


def extendBranchFromStep(branchObj, stepObj):
    taskObj = branchObj.task
    try:
        stepSuccessValues = stepObj.success.values()
        if len(stepSuccessValues) == 1 and len(stepSuccessValues[0]) == 1:  # sequential steps.
            nextStepName = stepSuccessValues[0][0]
            if nextStepName == "exit":
                branchObj.setLastStep(stepObj)
                return
            nextStep = Step(taskObj, nextStepName)
            if nextStepName == branchObj.mergeStep:
                branchObj.setLastStep(stepObj)
                mergeBranch = taskObj.branchesDict[nextStepName]
                if mergeBranch.dependenciesMakeComplete():
                    extendBranchFromStep(mergeBranch, nextStep)
            else:
                branchObj.addStep(nextStep)
                extendBranchFromStep(branchObj, nextStep)
            return
        if len(stepSuccessValues) > 1 or len(stepSuccessValues[0]) > 1:  # create new branches if forking
            branchObj.setLastStep(stepObj)
            makeForkBranches(taskObj, stepObj.success)
            return
        raise RuntimeError("Unsupported NEXT.SUCCESS configuration for the step '{0}': {1}"
                           .format(stepObj.stepName, stepObj.success))
    except:
        printErr("MakeBranches failed for task:  ", taskObj.taskName, stepObj.stepName)


def makeForkBranches(taskObj, forkingDictionary):  # make sure step is a forking one before you call it.
    for mergeStepName, branchNames in forkingDictionary.iteritems():
        if mergeStepName != "0":  # If 0, branches don't merge.
            mergeStep = Step(taskObj, mergeStepName)
            mergeBranch = Branch(mergeStep, "0")
            for branchName in branchNames:
                # don't makeBranches for mergeBranch until all dependencies are ready
                mergeBranch.dependencies.append(branchName)
        for branchName in branchNames:
            Branch(Step(taskObj, branchName), mergeStepName)  # create the branches
        for branchName in branchNames:
            branchObj = taskObj.branchesDict[branchName]
            extendBranchFromStep(branchObj, branchObj.steps[branchObj.currentStepName])


def runTask(taskObj):
    try:
        printInfo("Running task '{0}' with starting steps '{1}'.".format(taskObj.taskName, taskObj.start))
        startBranchNames = []
        for mergeStepName, branchNames in taskObj.start.iteritems():
            startBranchNames += branchNames
        if len(startBranchNames) > 1:
            branchQueue = Queue()
            for branchName in startBranchNames:
                branchQueue.put(taskObj.branchesDict[branchName])
            runBranchQueue(branchQueue)
        elif len(startBranchNames) == 1:
            branchName = startBranchNames[0]
            branch = taskObj.branchesDict[branchName]
            runBranch(branch)
        else:
            raise RuntimeError("No starting steps found for the task '{0}'".format(taskObj.taskName))
    except:
        printErr("Exception occurred in runTask for task '{0}'.".format(taskObj.taskName))


def runBranchQueue(branchQueue):
    try:
        for branchId in range(branchQueue.qsize()):
            branch = Thread(target=runOneBranchInQueue, args=(branchQueue,))
            branch.setDaemon(True)
            branch.start()
        branchQueue.join()
    except:
        printErr("forkBranches execution failed.")


def runOneBranchInQueue(branchQueue):
    if branchQueue.empty():
        printInfo("runBranchQueue - branchQueue is empty")
        return
    branch = None
    try:
        branch = branchQueue.get()
        printInfo("Running branchQueue branch: " + branch.branchName)
        runBranch(branch)
        branchQueue.task_done()
    except:
        printErr("branchQueue failed for branch: " + branch.branchName)


def runBranch(branchObj):
    if branchObj.currentStepName == "exit":
        branchObj.done = True
        return
    try:  # execute current step for branch
        taskObj = branchObj.task
        currentStep = branchObj.steps[branchObj.currentStepName]
        printInfo("Running step '{0}'. Failed cursors before resetting: '{1}'."
                  .format(currentStep.stepPath, currentStep.cursorFail))
        currentStep.cursorFail = []  # reset before running again
        exitCode = runStep(currentStep)

        if exitCode == 0:
            if branchObj.isLastStep():  # At branch last step. Start new branch.
                branchObj.done = True
                nextStepName = currentStep.success.values()[0][0]
                if len(currentStep.success.values()) == 1 and len(currentStep.success.values()[0]) == 1:
                    if nextStepName == "exit":
                        return
                    nextBranch = taskObj.branchesDict[nextStepName]
                    if branchObj.traceBranch:
                        nextBranch.traceBranch = True
                        taskObj.linkFailureHandling(nextStepName, currentStep.stepName)
                    if nextBranch.dependenciesExecutionComplete():
                        runBranch(nextBranch)
                elif len(currentStep.success.values()) > 1 or len(currentStep.success.values()[0]) > 1:
                    branchQueue = Queue()
                    for mergeStep, branchList in currentStep.success.iteritems():
                        for forkBranchName in branchList:
                            forkBranchName = taskObj.branchesDict[forkBranchName]
                            if branchObj.traceBranch:  # trace forked branches
                                forkBranchName.traceBranch = True
                                taskObj.linkFailureHandling(forkBranchName, currentStep.stepName)
                            branchQueue.put(forkBranchName)
                    # Chen: There is potential bug here.
                    # Consider this case: task.start:{m1:[s1,s2]}. steps{s1.next.success{0:[m1,m2]}}
                    # This code will run step m1 without checking the status of s2.
                    # If s2 is not ready, m1 should not start. Add dependencies checks here.
                    runBranchQueue(branchQueue)
                else:
                    raise RuntimeError("Step '{0}' has empty or unsupported success configurations '{1}'."
                                       .format(currentStep.stepName, currentStep.success))
            else:
                branchObj.moveToNextSuccess()
                if branchObj.traceBranch:
                    # When the recovery branch points back to the original failed step
                    if branchObj.currentStepName == branchObj.lastFail:
                        # This is to break the bridge between failed step and recovery step
                        # The idea is that recovery should happen once.
                        def removeLink(stepName):
                            delNext = taskObj.links.get(stepName)
                            if delNext is not None:
                                del taskObj.links[stepName]
                                for delN in delNext:
                                    removeLink(delN)

                        removeLink(currentStep.stepName)
                        branchObj.traceBranch = False
                    else:
                        taskObj.linkFailureHandling(branchObj.currentStepName, currentStep.stepName)
                runBranch(branchObj)
        else:  # when step failed
            if currentStep.stepName in branchObj.failedSteps or currentStep.nextFail == "exit":
                def traceBackRecoveryPath(stepName):
                    # Add all failed steps that can be reached from this stepName to
                    # TASK's failedStepNames for next TASK rerun
                    if stepName in taskObj.links.keys():
                        for name in taskObj.links[stepName]:
                            traceBackRecoveryPath(name)
                    elif stepName not in taskObj.failedStepNames:
                        taskObj.failedStepNames.append(stepName)

                traceBackRecoveryPath(currentStep.stepName)
            else:  # fail for the first time and try to recover
                branchObj.failAtStep(currentStep)
                runBranch(branchObj)
    except:
        currentStep = branchObj.steps[branchObj.currentStepName]
        printErr("RunBranch failed at step '{0}'.".format(currentStep.stepPath))


def runStep(step):
    global testMode
    try:
        exitCode, stepStartDate = 0, datetime.datetime.now()
        printInfo("RunStep for step '{0}' with cursors '{1}' using '{2}' thread(s)."
                  .format(step.stepName, step.cursor, step.thread))
        cursorQueue = Queue()
        for cur in step.cursor:
            cursorQueue.put(cur)
        runCursorQueue(step, cursorQueue, testMode)
        printInfo("Execution time for step '{0}' is: '{1}'."
                  .format(step.stepName, datetime.datetime.now() - stepStartDate))

        if len(step.cursorFail) == 0:
            return 0

        step.failureCount += 1
        printInfo("Step '{0}' failed with cursors '{1}'. Failure Count: {2}, Maximum failure allowed: {3}."
                  .format(step.stepPath, step.cursorFail, step.failureCount, step.maxFailures))
        step.cursor = step.cursorFail
        if step.failureCount < step.maxFailures:
            step.cursorFail = []
            time.sleep(step.waittime)
            return runStep(step)
        else:
            return 1
    except:
        printErr("RunStep failed for step '{0}'.".format(step.stepName))
        return 1


if __name__ == "__main__":
    main()
