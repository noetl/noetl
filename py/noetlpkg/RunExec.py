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
import sys, re, os, json, datetime, subprocess
from EvalJsonParser import *
from EvalRESTful import rest_eval


test = True

def runShell(task, step, cur):
    global config,testIt, log
    try:
        exitCode = -1
        curDatatype = getConfig(config,"WORKFLOW.TASKS." + str(task) + ".STEPS." + str(step) +".CALL.CURSOR.DATATYPE")
        dateFormat = getConfig(config,"WORKFLOW.TASKS." + str(task) + ".STEPS." + str(step) +".CALL.CURSOR.FORMAT")
        execLists = getConfig(config,"WORKFLOW.TASKS." + str(task) + ".STEPS." + str(step) +".CALL.EXEC.CMD")
        for cmdList in execLists:
            cmd = curPattern(" ".join(cmdList),cur,curDatatype,dateFormat)
            print(step, ":", cmd) # delete
            if (not testIt) and ("CONF_NOT_FOUND" not in cmd or "DATE_PATTERN_NOT_FOUND" not in cmd):
                exitCode = subprocess.call(cmd, shell=True)
                print(datetime.datetime.now()," - INFO - ","runShell exitCode: ",exitCode, " Command: " , cmd, file = log)
            elif testIt:
                print(datetime.datetime.now()," - INFO - ", "Executing command: " , cmd,file = log)
                exitCode = 0
    except:
        e = sys.exc_info()
        print(datetime.datetime.now()," - ERROR - ", "Command: " , cmd , " cursor value: " , cur , " ; was failed with exit code: " , exitCode , " error: " , e)
        print(datetime.datetime.now()," - ERROR - ", "Command: " , cmd , " cursor value: " , cur , " ; was failed with exit code: " , exitCode , " error: " , e,file = log)
        exitCode = 1
    return exitCode

def runRESTful(task, step, cur):
    global config,testIt, log
    try:
        exitCode = 0
        curDatatype = getConfig(config,"WORKFLOW.TASKS." + str(task) + ".STEPS." + str(step) +".CALL.CURSOR.DATATYPE")
        dateFormat = getConfig(config,"WORKFLOW.TASKS." + str(task) + ".STEPS." + str(step) +".CALL.CURSOR.FORMAT")
        restExec = getConfig(config,"WORKFLOW.TASKS." + str(task) + ".STEPS." + str(step) +".CALL.EXEC")

        print("restexec: ", restExec, " type: ", type(restExec))
        resp = rest_eval(**restExec)
        #resp = globals()[restFunc](restPath)
        print(datetime.datetime.now(),"Response: ", resp, " Type: ", type(resp))

    except:
        e = sys.exc_info()
        print(datetime.datetime.now()," - ERROR - ", "runRESTful was failed with exit code: " , restExec , " error: " , e)
        print(datetime.datetime.now()," - ERROR - ", "runRESTful was failed with exit code: " , restExec , " error: " , e,file = log)
        exitCode = -1
    return exitCode

def curPattern(valIn, cur = None, curType="date", dateFormat="%Y%m"):
    try:
        val = valIn
        varPattern = re.compile('.*?\[(.*?)\].*?')
        if cur is not None:
            varList=varPattern.findall(val)
            for varlistId in range(len(varList)):
                if curType.lower() == "date":
                    replaceCur = datetime.datetime.strptime(str(cur).strip(), dateFormat).date()
                    replaceFormat = varList[varlistId]
                    val = val.replace("["  + varList[varlistId] + "]", replaceCur.strftime(replaceFormat))
                elif curType.lower() == "integer":
                    val = val.replace("["  + varList[varlistId] + "]", cur)
        return val
    except:
        e = sys.exc_info()
        print(datetime.datetime.now()," - ERROR - ","curPattern failed: " , valIn , " cursor value: " , cur , " ; dateFormat: " , dateFormat , " error: ", e , file = log)
        return "DATE_PATTERN_NOT_FOUND"