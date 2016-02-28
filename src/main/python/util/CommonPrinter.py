from __future__ import print_function
import datetime
import sys


class NOETLPrinter:
    def __init__(self, log):
        self.log = log

    def err(self, msg):
        errorMsg = "{0} - ERROR - {1}".format(str(datetime.datetime.now()), " ".join(str(m) for m in msg))
        exc_type, exc_obj, exc_tb = sys.exc_info()
        exceptionLocation = "{0} @ line {1}: ".format(exc_tb.tb_frame.f_code.co_filename,
                                                      str(exc_tb.tb_lineno))
        print(errorMsg)
        print(exceptionLocation, exc_type, exc_obj)
        if self.log is not None:
            print(errorMsg, file=self.log)
            print(exceptionLocation, exc_type, exc_obj, file=self.log)

    def info(self, msg):
        infoMsg = "{0} - INFO - {1}".format(str(datetime.datetime.now()), " ".join(str(m) for m in msg))
        print(infoMsg)
        if self.log is not None:
            print(infoMsg, file=self.log)

    def close(self):
        if self.log is not None:
            self.log.close()


# define the default global printer
printer = NOETLPrinter(None)
