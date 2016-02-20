import datetime
import sys


def printErr(*msg):
    print(str(datetime.datetime.now()), " - ERROR - ", " ".join(str(m) for m in msg))
    exc_type, exc_obj, exc_tb = sys.exc_info()
    exceptionLocation = "{0} @ line {1}: ".format(exc_tb.tb_frame.f_code.co_filename,
                                                  str(exc_tb.tb_lineno))
    print(exceptionLocation, exc_type, exc_obj)


def printInfo(*msg):
    print(str(datetime.datetime.now()), " - INFO - ", " ".join(str(m) for m in msg))
