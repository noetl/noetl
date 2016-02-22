import threading
from threading import Thread

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
        action = "{0}(\"{1}\",\"{2}\",\"{3}\")" \
            .format(stepObj.action, stepObj.task.taskName, stepObj.stepName, cursor)
        printInfo("At thread {0}, running cursorQueue job: {1}".format(threading.current_thread(), action))
        exitCode = eval(action)
        if exitCode != 0 and cursor not in stepObj.cursorFail:
            printInfo("Execution failed for '{0}'".format(action))
            stepObj.cursorFail.append(cursor)
    except:
        printErr("Queue job failed.")
        exitCode = 1
    cursorQueue.task_done()
    return exitCode
