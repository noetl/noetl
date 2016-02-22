import threading
from threading import Thread

from execution import ExecutionActionsUtil
from execution.ExecutionActionsForProduction import SupportedProductActions
from execution.ExecutionActionsForTests import SupportedTestActions
from util.CommonPrinter import *
from util.CommonPrinter import printErr


# IMPORTANT CHANGE!!!! ONLY PASS CURSOR LIST HERE.
def runThreads(config, stepObj, cursorQueue):
    try:
        exitCode = 0
        for i in range(cursorQueue.qsize()):
            th = Thread(target=runQueue, args=(config, stepObj, cursorQueue,))
            th.setDaemon(True)
            th.start()
        cursorQueue.join()
    except:
        printErr('Run threads in parallel failed for the cursor queue [ {0} ]'.format("\n\t".join(cursorQueue)))
        exitCode = -1
    return exitCode


def runQueue(config, stepObj, cursorQueue):
    if cursorQueue.empty():
        printInfo("runQueue - cursorQueue is empty")
        return -1
    try:
        cursor = cursorQueue.get()
        actionContext = getActionContext(stepObj.action)
        if actionContext == "":
            raise RuntimeError(
                "The action '{0}' for the step '{1}' is not supported.".format(stepObj.action, stepObj.stepPath))
        action = "{0}.{1}(\"{2}\",\"{3}\",\"{4}\")" \
            .format(actionContext, stepObj.action, stepObj.task.taskName, stepObj.stepName, cursor)
        printInfo("At thread {0}, running cursorQueue job: {1}".format(threading.current_thread(), action))
        exitCode = eval(action)
        if exitCode != 0 and cursor not in stepObj.cursorFail:
            printInfo("ExitCode is {1}. Execution failed for '{0}'".format(action, exitCode))
            stepObj.cursorFail.append(cursor)
    except:
        printErr("Queue job failed.")
        exitCode = 1
    cursorQueue.task_done()
    return exitCode


def getActionContext(action):
    productActions = ExecutionActionsUtil.getAllCallableMethods(SupportedProductActions())
    if action in productActions:
        return "SupportedProductActions"
    testActions = ExecutionActionsUtil.getAllCallableMethods(SupportedTestActions())
    if action in testActions:
        return "SupportedTestActions"
    return ""
