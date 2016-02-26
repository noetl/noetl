import threading
from threading import Thread

from src.main.python.execution import ExecutionActionsUtil
from src.main.python.execution.ExecutionActionsForProduction import SupportedProductActions
from src.main.python.execution.ExecutionActionsForTests import SupportedTestActions
from src.main.python.util.CommonPrinter import *


def runCursorQueue(stepObj, cursorQueue, testMode):
    if cursorQueue is None:
        return
    try:
        threads = int(stepObj.thread) if stepObj.thread.isdigit() else 0
        if threads <= 1:
            printInfo("Use single thread to process.")
            for i in range(cursorQueue.qsize()):
                runOneCursorInQueue(stepObj, cursorQueue, testMode)
        else:
            printInfo("Spawning {0} threads to process for the step '{1}'.".
                      format(threads, stepObj.stepPath))
            semaphore = threading.Semaphore(threads)
            cursorFailUpdate = threading.Lock()
            for i in range(cursorQueue.qsize()):
                semaphore.acquire()
                threadCount = str(threading.active_count())
                # TODO: should be able to reuse the thread like a thread pool or try other implementation
                th = Thread(name="ThreadCount-" + threadCount, target=runOneCursorInQueue,
                            args=(stepObj, cursorQueue, testMode, semaphore, cursorFailUpdate))
                th.setDaemon(True)
                th.start()
            cursorQueue.join()
    except:
        printErr('Run threads in parallel failed for the cursor queue [ {0} ]'.format("\n\t".join(cursorQueue)))


def runOneCursorInQueue(stepObj, cursorQueue, testMode, semaphore=None, cursorFailUpdate=None):
    if stepObj is None or cursorQueue is None or cursorQueue.empty():
        printInfo("step is None or cursorQueue is empty")
        return
    cursor = None
    actionWOContext = ""
    try:
        cursor = cursorQueue.get()
        context = __getActionContext(stepObj.action)
        if context == "":
            raise RuntimeError(
                "Action '{0}' for step '{1}' is not supported.".format(stepObj.action, stepObj.stepPath))
        actionFormat = "{0}({1},\"{2}\",{3})"
        if not isinstance(cursor, basestring):  # don't surround cursor with quotes if not string type
            actionFormat = "{0}({1},{2},{3})"
        actionWOContext = actionFormat.format(stepObj.action, "stepObj", cursor, testMode)
        actionWContext = "{0}.{1}".format(context, actionWOContext)
        threadName = str(threading.current_thread())
        sys.stdout.flush()
        printInfo('Thread-{0} running "{1}"'.format(threadName, actionWOContext))
        sys.stdout.flush()
        if eval(actionWContext) != 0:
            __updateStepFailedCursors(cursor, cursorFailUpdate, stepObj)
            printInfo("Step '{0}' failed for action '{1}'.".format(stepObj.stepPath, actionWOContext))
    except:
        __updateStepFailedCursors(cursor, cursorFailUpdate, stepObj)
        printInfo("RunQueue failed at step '{0}' for action '{1}'.".format(stepObj.stepPath, actionWOContext))
    finally:
        if semaphore is not None:
            semaphore.release()
        cursorQueue.task_done()


def __updateStepFailedCursors(cursor, cursorFailUpdate, stepObj):
    if cursorFailUpdate is not None:
        try:
            cursorFailUpdate.acquire()
            if cursor not in stepObj.cursorFail:
                stepObj.cursorFail.append(cursor)
        finally:
            cursorFailUpdate.release()
    else:
        stepObj.cursorFail.append(cursor)


def __getActionContext(action):
    productActions = ExecutionActionsUtil.getAllCallableMethods(SupportedProductActions())
    if action in productActions:
        return "SupportedProductActions"
    testActions = ExecutionActionsUtil.getAllCallableMethods(SupportedTestActions())
    if action in testActions:
        return "SupportedTestActions"
    return ""
