import argparse
import json
import os
import time
from Queue import Queue
from threading import Thread
from component.Branch import Branch
from component.Step import Step
from component.Task import Task
from execution.QueueExecution import runCursorQueue
from util.CommonPrinter import *
from util.NOETLJsonParser import NOETLJsonParser
from util.Tools import processConfRequest

testMode = False


def main(argv=None):
    try:
        parser = argparse.ArgumentParser(description="""
        Run noetl.""", usage='%(prog)s [OPTIONS]', formatter_class=argparse.RawTextHelpFormatter)
        parser.add_argument("--conf_file", help="specify the path to the noetl configuration file.", default="")

        args = parser.parse_args()
        print("Number of input arguments is: {0}\nGiven arguments are: {1}"
              .format(str(len(sys.argv)), str(json.dumps(vars(args)))))

        configFilePath = args.conf_file
        _main(configFilePath, False)
        return 0
    except:
        printer.err("NOETL Failed.")
        printer.close()
        return 1


def _main(configFilePath, forUnitTest):
    global testMode
    config = NOETLJsonParser(configFilePath).getConfig()
    if not forUnitTest:
        initiateLog(config, 0)
    testMode = True if processConfRequest(config, "WORKFLOW.TEST.FLAG") == "True" else False
    if testMode:
        return doTest(config)
    else:
        task = Task("start", config)
        getTask(config, task)


def doTest(config):
    try:
        printer.info("In test mode...")
        taskList = processConfRequest(config, "WORKFLOW.TASKS")
        printer.info("LIST of TASKS:\n" + str(taskList))

        task = Task("start", config)
        getTask(config, task)
    except:
        printer.err("Test mode failed.")


def getTask(config, taskObj):
    try:
        printer.info("Getting task '{0}' with description '{1}'. Next task is '{2}'"
                     .format(taskObj.taskName, taskObj.taskDesc, taskObj.nextSuccess))
        if taskObj.taskName == "exit":
            return
        # Make branches for the task before execution.
        startDictValues = taskObj.start.values()
        __configurationValidationCheck(startDictValues, taskObj)
        if len(startDictValues) == 1 and len(startDictValues[0]) == 1:
            stepObj = Step(taskObj, startDictValues[0][0])
            # if taskObj.start.keys()[0] != "0":
            #     raise RuntimeError("You cannot define merge step when there is only one start step. "
            #                        "Alternatively, you can move the merge step to the step's next.success")
            branch = Branch(stepObj, taskObj.start.keys()[0])
            extendBranchFromStep(branch, stepObj)
        elif taskObj.taskName == "start" and len(startDictValues) == 0:  # allow empty start dictionary for start task
            getTask(config, Task(taskObj.nextSuccess, config))
            return
        elif len(startDictValues) > 1 or len(startDictValues[0]) > 1:  # forking branches
            makeForkBranches(taskObj, taskObj.start)

        # start task execution.
        taskStartDate = datetime.datetime.now()
        runTask(taskObj)
        printer.info("Execution time for task '{0}' is: {1}."
                     .format(taskObj.taskName, datetime.datetime.now() - taskStartDate))
        if len(taskObj.failedStepNames) > 0:
            printFailedInfo(taskObj)
            getTask(config, Task(taskObj.nextFail, config))
        else:
            printer.info("Task '{0}' finished successfully.".format(taskObj.taskName))
            getTask(config, Task(taskObj.nextSuccess, config))
    except:
        printer.err("getTask failed for task '{0}'".format(str(taskObj)))


def __configurationValidationCheck(startDictValues, taskObj):
    checkUniqueSteps = set()  # This feature will be supported in the further version.
    for steps in startDictValues:
        for step in steps:
            if step in checkUniqueSteps:
                raise RuntimeError("The step '{0}' exists more than once in your task start config"
                                   .format(step, taskObj.start))
            else:
                checkUniqueSteps.add(step)
    for step in taskObj.start.keys():
        if step in checkUniqueSteps:
            raise RuntimeError("The step '{0}' exists more than once in your task start config"
                               .format(step, taskObj.start))
        else:
            checkUniqueSteps.add(step)


def printFailedInfo(taskObj):
    printer.info("FAILURE: Task '{0}' failed with step(s): '{1}'."
                 .format(taskObj.taskName, ",".join(taskObj.failedStepNames)))
    for failedStep in taskObj.failedStepNames:
        printer.info('FAILURE: Step "{0}" failed with cursors "{1}".'
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
        printer.err("MakeBranches failed for task:  ", taskObj.taskName, stepObj.stepName)


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
    printer.info("Running task '{0}' with starting steps '{1}'.".format(taskObj.taskName, taskObj.start))
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


def runBranchQueue(branchQueue):
    try:
        for branchId in range(branchQueue.qsize()):
            branch = Thread(target=runOneBranchInQueue, args=(branchQueue,))
            branch.setDaemon(True)
            branch.start()
        branchQueue.join()
    except:
        printer.err("forkBranches execution failed.")


def runOneBranchInQueue(branchQueue):
    if branchQueue.empty():
        printer.info("runBranchQueue - branchQueue is empty")
        return
    branch = None
    try:
        branch = branchQueue.get()
        printer.info("Running branchQueue branch: " + branch.branchName)
        runBranch(branch)
        branchQueue.task_done()
    except:
        printer.err("branchQueue failed for branch: " + branch.branchName)


def runBranch(branchObj):
    if branchObj.currentStepName == "exit":
        branchObj.done = True
        return
    try:  # execute current step for branch
        taskObj = branchObj.task
        currentStep = branchObj.steps[branchObj.currentStepName]
        printer.info("Running step '{0}'. Failed cursors before resetting: '{1}'."
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
                    # TODO: The problem is that we are creating steps without checking their existence.
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
        # branch.currentStepObj might not be available here. Don't output it.
        printer.err(
            "RunBranch '{0}' failed at step '{1}'.".format(branchObj.branchName, branchObj.currentStepName))


def runStep(step):
    global testMode
    try:
        exitCode, stepStartDate = 0, datetime.datetime.now()
        printer.info("RunStep for step '{0}' with cursors '{1}' using '{2}' thread(s)."
                     .format(step.stepName, step.cursor, step.thread))
        cursorQueue = Queue()
        for cur in step.cursor:
            cursorQueue.put(cur)
        runCursorQueue(step, cursorQueue, testMode)
        printer.info("Execution time for step '{0}' is: '{1}'."
                     .format(step.stepName, datetime.datetime.now() - stepStartDate))

        if len(step.cursorFail) == 0:
            return 0

        step.failureCount += 1
        printer.info("Step '{0}' failed with cursors '{1}'. Failure Count: {2}, Maximum failure allowed: {3}."
                     .format(step.stepPath, step.cursorFail, step.failureCount, step.maxFailures))
        step.cursor = step.cursorFail
        if step.failureCount < step.maxFailures:
            step.cursorFail = []
            time.sleep(step.waittime)
            return runStep(step)
        else:
            return 1
    except:
        printer.err("RunStep failed for step '{0}'.".format(step.stepName))
        return 1


def initiateLog(config, logId):
    batchDateTime = datetime.datetime.now()
    try:
        logConfig = processConfRequest(config, "LOGGING.{0}.FILE".format(logId))
        logDir = logConfig["DIRECTORY"]
        if logDir.strip() == "":
            logDir = os.path.dirname(__file__)
        if not os.path.exists(logDir):
            os.makedirs(logDir)

        extension = logConfig.get("EXTENTION")
        if extension is None:
            extension = ""
        pattern = logConfig.get("PATTERN")
        if pattern is not None and pattern.lower() == "datetime":
            extension = batchDateTime.strftime('-%Y%m%d%H%M%S') + "." + extension

        logFile = logDir + os.sep + logConfig["NAME"] + extension
        print("Using LogFile: {0}".format(logFile))
        global printer
        log = open(logFile, "w", 0)
        printer = NOETLPrinter(log)
    except:
        e = str(sys.exc_info()[0]) + str(sys.exc_info()[1]) + str(sys.exc_info()[2])
        print("{0} - ERROR - Error raised when initiating the main log handler: ".format(str(batchDateTime)), str(e))


if __name__ == "__main__":
    sys.exit(main())
    # _main("/Users/chenguo/Documents/noetl/noetl/src/test/resources/noetlTest_simpleFork_1.json", False)
