from component.Task import Task
from src.main.python.util.CommonPrinter import *
from util.NOETLJsonParser import NOETLJsonParser
from util.Tools import processConfRequest


def main(argv=None):
    if argv is None:
        argv = sys.argv
    config = NOETLJsonParser(str(argv[1])).getConfig()
    testIt = True if processConfRequest(config, "WORKFLOW.TEST.FLAG") == "True" else False
    if testIt:
        doTest(str(argv[1]))
    else:
        try:
            printInfo("LIST of TASKS", processConfRequest(config, "WORKFLOW.TASKS", "LIST_INDEX"))

            task = Task("start", config)
            # getTask(task)
        except:
            printErr("Failed")


if __name__ == "__main__":
    main()
