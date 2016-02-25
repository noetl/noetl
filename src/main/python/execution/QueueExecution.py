import threading
from threading import Thread
from src.main.python.execution import ExecutionActionsUtil
from src.main.python.execution.ExecutionActionsForProduction import SupportedProductActions
from src.main.python.execution.ExecutionActionsForTests import SupportedTestActions
from src.main.python.util.CommonPrinter import *


def runThreads(config, stepObj, cursorQueue, testMode):
    try:
        if cursorQueue is None:
            return 0
        threads = int(stepObj.thread) if stepObj.thread.isdigit() else 0
        if threads <= 1:
            printInfo("Use single thread to process.")
            for i in range(cursorQueue.qsize()):
                runQueue(config, stepObj, cursorQueue, testMode)
        else:
            printInfo("Spawning {0} threads to process for the step '{1}'.".
                      format(threads, stepObj.stepPath))
            semaphore = threading.Semaphore(threads)
            cursorFailUpdate = threading.Lock()
            for i in range(cursorQueue.qsize()):
                semaphore.acquire()
                threadCount = str(threading.active_count())
                # TODO: should be able to reuse the thread like a thread pool or try other implementation
                th = Thread(name="ThreadCount-" + threadCount, target=runQueue,
                            args=(config, stepObj, cursorQueue, testMode, semaphore, cursorFailUpdate))
                th.setDaemon(True)
                th.start()
            cursorQueue.join()
        return 0
    except:
        printErr('Run threads in parallel failed for the cursor queue [ {0} ]'.format("\n\t".join(cursorQueue)))
        return 1


def runQueue(config, stepObj, cursorQueue, testMode, semaphore=None, cursorFailUpdate=None):
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
        current_thread = str(threading.current_thread())
        sys.stdout.flush()
        print("CRT_THD: " + current_thread)
        printInfo('At thread {0}, running "{1}"'.format(current_thread, actionWContext))
        sys.stdout.flush()
        exitCode = eval(actionWContext)
        sys.stdout.flush()
        print("Finished step '{0}' with cursor '{1}.".format(stepObj.stepPath, cursor))
        sys.stdout.flush()
        if exitCode != 0 and cursor not in stepObj.cursorFail:
            printInfo("ExitCode is {1} for '{0}'".format(actionWOContext, exitCode))
            if cursorFailUpdate is not None:
                cursorFailUpdate.acquire()
            stepObj.cursorFail.append(cursor)
            if cursorFailUpdate is not None:
                cursorFailUpdate.release()
    except:
        if cursorFailUpdate is not None and cursorFailUpdate.locked():
            cursorFailUpdate.release()
        printErr("Queue job failed.")
    if semaphore is not None:
        semaphore.release()
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
