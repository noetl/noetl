import re
import subprocess

from src.main.python.util import Tools
from src.main.python.util.Tools import *


class SupportedProductActions:
    @staticmethod
    def runShell(stepObj, currentCursor, testMode):
        info = ""
        try:
            for cmdList in stepObj.execLists:
                dereferenceCmd, success = dereferenceCursor(" ".join(cmdList), currentCursor, stepObj.cursorDataType,
                                                            stepObj.cursorFormat)
                if not success:
                    return 1
                info = "Executing '{0}' for step '{1}'.".format(dereferenceCmd, stepObj.stepPath)
                printInfo(info)
                if testMode:
                    return 0
                else:
                    exitCode = subprocess.call(dereferenceCmd, shell=True)
                    printInfo("runShell exitCode: {0} for the Command {1}.".format(exitCode, dereferenceCmd))
        except:
            printErr(info + " failed.")
            return 1


def dereferenceCursor(cmd, origCursorValue, cursorType, cursorDateFormat):
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
        printErr(
            'Dereference [cursor] in command "{0}" failed for the cursor value "{1}" with format "{2}"'
                .format(origCmd, origCursorValue, cursorDateFormat))
        return origCmd, False
