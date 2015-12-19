#!/usr/bin/python
#
# TITLE: Evaluate Json Parser
# AUTHORS: Alexey Kuksin, Casey Takahashi
# DATE: 01-08-2015
# OBJECTIVE: Manage process execution 
#   
#   Copyright 2015 ALEXEY KUXIN
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from __future__ import print_function
from EvalJsonParser import *
import logging

def initiateLog(logId, batchDateTime):
    try:
        log = logging.getLogger(getConfig(config,"LOGGING." + logId +".NAME"))
        logDir = getConfig(config,"LOGGING." + logId +".FILE.DIRECTORY","None")
        if not os.path.exists(logDir):
            os.makedirs(logDir)
        logFile = logDir + os.sep + getConfig(config,"LOGGING." + logId +".FILE.NAME") + \
             (batchDateTime.strftime('-%Y%m%d%H%M%S') if getConfig(config,"LOGGING." + logId +".FILE.PATTERN") in "datetime" else "") + \
             "." + getConfig(config,"LOGGING." + logId +".FILE.EXTENTION")
        log = open(logFile, "w",0)
        print(batchDateTime," - INFO - ","LogFile",logFile)
        return log, logFile, config,0
    except:
        e = str(sys.exc_info()[0]) + str(sys.exc_info()[1]) + str(sys.exc_info()[2])
        print(batchDateTime," - ERROR - ","Error raised when initiating the main log handler: ",logFile,e)
        return None, None, None, 1