import re
import subprocess

import requests

from util import Tools
from util.Tools import *


class SupportedProductActions:
    @staticmethod
    def runShell(stepObj, currentCursor, testMode):
        info = ""
        try:
            for cmdList in stepObj.execLists:
                dereferenceCmd, success = SupportedProductActions.__dereferenceCursor(
                    " ".join(cmdList), currentCursor, stepObj.cursorDataType, stepObj.cursorFormat)
                if not success:
                    return 1
                info = "Executing '{0}' for step '{1}'.".format(dereferenceCmd, stepObj.stepPath)
                printer.info(info)
                if testMode:
                    return 0
                else:
                    exitCode = subprocess.call(dereferenceCmd, shell=True)
                    printer.info("runShell exitCode: {0} for the Command {1}.".format(exitCode, dereferenceCmd))
                    return exitCode
        except:
            printer.err(info + " failed.")
            return 1

    @staticmethod
    def runRESTful(task, stepObj, cur):
        try:
            restExec = stepObj.callExec
            print("The restexec dictionary is: " + str(restExec))
            resp = SupportedProductActions.rest_eval(**restExec)
            printer.info("RESTful Response: {0} Type: {1}".format(str(resp), str(type(resp))))
            return 0
        except:
            printer.err("runRESTful failed.")
            return 1

    @staticmethod
    def __dereferenceCursor(cmd, origCursorValue, cursorType, cursorDateFormat):
        if origCursorValue is None:
            return cmd, False
        origCmd = cmd
        try:
            cmdPattern = re.compile('.*?\[(.*?)\].*?')
            conversions = cmdPattern.findall(cmd)
            for conversion in conversions:
                if cursorType.lower() == "date":
                    dateObj = Tools.stringToDate(origCursorValue, cursorDateFormat)
                    convertedString = dateObj.strftime(conversion)
                    cmd = cmd.replace("[" + conversion + "]", convertedString)
                elif cursorType.lower() == "integer":
                    cmd = cmd.replace("[" + conversion + "]", origCursorValue)
                else:
                    raise RuntimeError("Unknown cursorType '{0}'".format(cursorType))
            return cmd, True
        except:
            printer.err(
                'Dereference [cursor] in command "{0}" failed for the cursor value "{1}" with format "{2}"'
                    .format(origCmd, origCursorValue, cursorDateFormat))
            return origCmd, False

    @staticmethod
    def rest_eval(**kwarg):
        if "get_contexts" in kwarg["FUNC"]:
            return requests.get(kwarg["PATH"])
        if "create_context" in kwarg["FUNC"]:
            return requests.get(kwarg["PATH"], kwarg["PARAMS"])
        if "delete_context" in kwarg["FUNC"]:
            return requests.get(kwarg["PATH"])
        if "deploy_jars" in kwarg["FUNC"]:
            return requests.get(kwarg["PATH"], kwarg["JAR"])
        if "jars" in kwarg["FUNC"]:
            return requests.get(kwarg["PATH"])
        if "jobs" in kwarg["FUNC"]:
            return requests.get(kwarg["PATH"])
        if "submit_job" in kwarg["FUNC"]:
            return requests.post(kwarg["PATH"], params=kwarg["PARAMS"], data=kwarg["DATA"])
        if "check_job_status" in kwarg["FUNC"]:
            return requests.post(kwarg["PATH"] + "/" + kwarg["JOBID"])
        else:
            return "UNKNOWN REQUEST"
