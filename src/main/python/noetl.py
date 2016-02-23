from component.Branch import Branch
from component.Step import Step
from component.Task import Task
from src.main.python.util.CommonPrinter import *
from util.NOETLJsonParser import NOETLJsonParser
from util.Tools import processConfRequest

FIRST_TASK_NAME = "start"


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
    try:
        exitCode = taskObj.taskName
        if isinstance(taskObj.start, dict) and (taskObj.taskName != FIRST_TASK_NAME) and (
                    taskObj.taskName != "exit"):  # validate task and create branchesDict
            if len(taskObj.start.values()) > 1 or len(taskObj.start.values()[0]) > 1:  # forking branches
                for merge in taskObj.start.keys():
                    if merge != "0":  # if 0, branches don't merge
                        mergeStep = Step(taskObj, merge)
                        mergeBranch = Branch(taskObj, merge, "0")
                        mergeBranch.steps[merge] = mergeStep
                        taskObj.stepObs[merge] = mergeStep  # add step object to task
                        taskObj.branchesDict[merge] = mergeBranch
                        taskObj.branchValidDict[merge] = False
                        for b in taskObj.start[merge]:
                            mergeBranch.dependencies.append(b)  # put forked branch names in mergeBranch dependencies
                            taskObj.branchValidDict[b] = False
                for mergeStep in taskObj.start.keys():
                    for branchName in taskObj.start[mergeStep]:
                        newBranch = Branch(taskObj, branchName, mergeStep)
                        step = Step(taskObj, branchName)
                        newBranch.steps[branchName] = step
                        taskObj.stepObs[branchName] = step  # add step object to task
                        taskObj.branchesDict[branchName] = newBranch
                        exitCode = makeBranches(taskObj, newBranch, step)  # create branch for each forked step
            elif (len(taskObj.start.values()) == 1) and (len(taskObj.start.values()[0]) == 1):
                firstStep = taskObj.start.values()[0][0]
                step = Step(taskObj, firstStep)
                if taskObj.start.keys()[0] != "0":
                    raise "You cannot define merge step when there is only one start step." \
                          "This feature is currently not supported. Alternatively, you can move the merge step to" \
                          "next.success"
                branch = Branch(taskObj, firstStep, "0")
                branch.steps[firstStep] = step
                taskObj.stepObs[firstStep] = step  # add step object to task
                taskObj.branchesDict[firstStep] = branch
                taskObj.branchValidDict[firstStep] = False
                exitCode = makeBranches(taskObj, branch, step)  # create branch for each forked step
                # CHEN: if condition not complete. This will fail start{a:[]}.
        printInfo("Task: ", taskObj.taskName, ", where next task: ", taskObj.nextTask,
                  ", and task description: ", taskObj.taskDesc)
        if (str(taskObj.taskName) == "exit") or ("CONF_NOT_FOUND" in taskObj.taskName):
            exitCode = str(taskObj.taskName)
        else:
            exitCode = runTask(taskObj)
            # for branch in task.branchesDict.values(): # delete
            # print("branch:", branch.branchName, " steps:", branch.steps.keys(), " last step:", branch.lastStep) # delete
            if (exitCode == "CONF_NOT_FOUND") or (len(taskObj.restart) != 0):
                printInfo("Task Failed: ", taskObj.taskName, ", Re-Start at steps: ", taskObj.restart)
                for st in taskObj.restart:
                    printInfo("STEP: ", st, " failed with cursors ", taskObj.stepObs[st].cursor)
                    exitCode = getTask(Task(taskObj.nextFail, config), testMode)
                else:
                    exitCode = getTask(Task(taskObj.nextTask, config), testMode)
    except:
        printErr("getTask failed for task '{0}'".format(str(taskObj)))
        return 1


def makeBranches(taskObj, newBranch, step):
    pass


def runTask(taskObj):
    pass


if __name__ == "__main__":
    sys.exit(main())
