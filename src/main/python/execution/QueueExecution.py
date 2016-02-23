import threading
from threading import Thread
from src.main.python.execution import ExecutionActionsUtil
from src.main.python.execution.ExecutionActionsForProduction import SupportedProductActions
from src.main.python.execution.ExecutionActionsForTests import SupportedTestActions
from src.main.python.util.CommonPrinter import *


# IMPORTANT CHANGE!!!! ONLY PASS CURSOR LIST HERE.
def runThreads(config, stepObj, cursorQueue, testMode):
    try:
        for i in range(cursorQueue.qsize()):
            # TODO: limit number of threads by stepObj.thread
            th = Thread(target=runQueue, args=(config, stepObj, cursorQueue, testMode,))
            th.setDaemon(True)
            th.start()
        cursorQueue.join()
        return 0
    except:
        printErr('Run threads in parallel failed for the cursor queue [ {0} ]'.format("\n\t".join(cursorQueue)))
        return 1


def runQueue(config, stepObj, cursorQueue, testMode):
    exitCode = 1
    if cursorQueue.empty():
        printInfo("runQueue - cursorQueue is empty")
        return exitCode
    try:
        cursor = cursorQueue.get()
        context = getActionContext(stepObj.action)
        if context == "":
            raise RuntimeError(
                "The action '{0}' for the step '{1}' is not supported.".format(stepObj.action, stepObj.stepPath))
        actionFormat = "{0}({1},\"{2}\",{3})"
        if not isinstance(cursor, basestring):
            actionFormat = "{0}({1},{2},{3})"
        actionWOContext = actionFormat.format(stepObj.action, "stepObj", cursor, testMode)
        actionWContext = "{0}.{1}".format(context, actionWOContext)
        printInfo('At thread {0}, running "{1}"'.format(threading.current_thread(), actionWContext))
        exitCode = eval(actionWContext)
        if exitCode != 0 and cursor not in stepObj.cursorFail:
            printInfo("ExitCode is {1} for '{0}'".format(actionWOContext, exitCode))
            stepObj.cursorFail.append(cursor)
    except:
        printErr("Queue job failed.")
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
