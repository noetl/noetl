#!/usr/bin/python
#
# TITLE: noetl
# AUTHORS: Alexey Kuksin, Casey Takahashi
# DATE: 16-08-2015
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
import sys, os, datetime, time, re, logging, json, subprocess
from Queue import *
from threading import Thread
from EvalJsonParser import parseConfig
from distutils.command.config import config

bug7980 = datetime.datetime.strptime("20110101","%Y%m%d") #bug http://bugs.python.org/issue7980
batchDateTime = datetime.datetime.now()

def getConfig(cfg,confRequest, confCase=None):
    try:
        confList = confRequest.split(".")
        for label in confList:
            if isinstance(cfg, dict):
                if label in cfg:
                    cfg = cfg[label]
                else:
                    return "CONF_NOT_FOUND"
            elif isinstance(cfg, list):
                if not isinstance(label, unicode):
                    label = unicode(label, 'utf-8')
                if label.isnumeric():
                    i = int(label)
                    cfg = cfg[i]
        if confCase == "LIST_INDEX" and isinstance(cfg, list):
            cfg = [idx for idx,val in enumerate(cfg)]
    except:
        e = str(sys.exc_info()[0]) + str(sys.exc_info()[1]) + str(sys.exc_info()[2])
        # print(datetime.datetime.now()," - ERROR - ","Error raised in getConfig with: ", e , " confRequest: " , confRequest, type(cfg))
        print(datetime.datetime.now()," - ERROR - ","Error raised in getConfig with: ", e , " confRequest: " , confRequest, type(cfg),file = log)
        cfg = "CONF_NOT_FOUND"
    return cfg

def getCursor(cursor, datatype, increment, dateFormat='%Y%m'):
    try:
        for curId,curVal in enumerate(cursor):
            if ":" in curVal:
                curList = curVal.split(":") 
                if datatype.lower() == "date" and len(curList) == 2 and isinstance(datetime.datetime.strptime(curList[0], dateFormat), datetime.datetime) and isinstance(datetime.datetime.strptime(curList[1], dateFormat), datetime.datetime):
                    cursor[curId] = curList[0]
                    incType = increment[len(increment) - 1].lower()
                    incAmt = int(increment[0:(len(increment) - 1)])
                    partialCursor = addTime(curList[0], curList[1], incAmt, incType, dateFormat)
                    for cur in partialCursor:
                        if cur not in cursor:
                            cursor.append(cur)
                elif datatype.lower() == "integer" and len(curList) == 2:
                    cursor[curId] = curList[0]
                    increment = int(increment)
                    i = int(curList[0]) + increment
                    while i < (int(curList[1])+1):
                        cursor.append(str(i))
                        i += increment
        return sorted(set(cursor)) 
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","getCursor failed with error: ",e)
        return sorted(set(cursor))
    
def addTime(strDate1, strDate2, increment, incType='m', dateFormat="%Y%m"):
    try:
        date1, date2 = datetime.datetime.strptime(strDate1,dateFormat), datetime.datetime.strptime(strDate2,dateFormat)
        currentCursor = []
        timeDelta = datetime.timedelta(days=increment)
        while date1 <= date2 - timeDelta:
            currentCursor.append(date1.strftime(dateFormat))
            if incType == 'y':
                date1 = datetime.datetime(date1.year+increment, date1.month, date1.day)
            elif incType == 'm':
                date1 = datetime.datetime(date1.year+((date1.month + increment-1)//12), ((date1.month+increment-1)%12)+1, date1.day)
            elif incType == 'd':
                date1 = date1 + timeDelta
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","addTime failed with error: ",e)
    return currentCursor

def inititateRep(batchDateTime):
    global repid, config
    try:
        repDir = getConfig(config,"REPORT.FILE.DIRECTORY","None")
        if not os.path.exists(repDir):
            os.makedirs(repDir)
        repFile = repDir + os.sep + str(getConfig(config,"REPORT.FILE.NAME"))
        repid = open(repFile, "w")
        repid.write(batchDateTime)
        repid.close()
    except:
        return False
    return True

def initiateLog(logId): 
    global log, logFile, config
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
    except:
        e = str(sys.exc_info()[0]) + str(sys.exc_info()[1]) + str(sys.exc_info()[2]) 
        print(batchDateTime," - ERROR - ","Error raised when initiating the main log handler: ",logFile,e)
    return 0

def sendMail(confTag, confTagId):
    global config
    mailSubject = str(getConfig(config,"LOGGING.0.MAIL.SUBJECT"))
    mailList = str(getConfig(config,"LOGGING.0.MAIL.LIST"))
    mailCmd =  str(getConfig(config,"LOGGING.0.MAIL.CMD"))  + ' "' + mailSubject + '" "' + mailList + '" < ' + logFile
    try:
        exitCode = subprocess.call(mailCmd, shell=True)
        print(datetime.datetime.now()," - INFO - ","Mail sent as: ", exitCode, " cmd: ", mailCmd,file = log) 
    except:
        print(datetime.datetime.now()," - ERROR - ","Mailing send error code: ", exitCode, " cmd: ", mailCmd,file = log)

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

def getWaittime(waittime):
    try:
        measure = waittime[len(waittime) - 1].lower()
        timeLength = int(waittime[0:(len(waittime) - 1)])
        if measure == 's':
            return timeLength
        elif measure == 'm':
            return timeLength*60
        elif measure == 'h':
            return timeLength*60*60
    except:
        e = sys.exc_info()
        print(datetime.datetime.now()," - ERROR - ","getWaittime failed: ", waittime, " error: ", e , file = log)

def runShell(task, step, cur):
    global config,testIt
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

def runQueue(step, cursorQueue):
    global config
    if cursorQueue.empty():
        print(datetime.datetime.now(),"runQueue - cursorQueue is empty",file = log)
        return -1
    try:
        job = cursorQueue.get() 
        # print(datetime.datetime.now()," - INFO - ","Running cursorQueue job: ",job)
        print(datetime.datetime.now()," - INFO - ","Running cursorQueue job: ",job,file = log)
        jobsplit = job.split(".")
        exitCode, taskId, stepId, cur = 0, jobsplit[1].rstrip(), jobsplit[3].rstrip(), jobsplit[5].rstrip() 
        ACTION = getConfig(config,"WORKFLOW.TASKS." + str(taskId) + ".STEPS." + str(stepId) +".CALL.ACTION")
        if "CONF_NOT_FOUND" not in ACTION:
            exitCode = eval(ACTION + "(\"" + str(taskId) + "\",\"" + str(stepId) + "\",\"" + str(cur) + "\")") 
            if (exitCode != 0) and (cur not in step.cursorFail): 
                step.cursorFail.append(cur) # if any cursors in cursorFail after step is done running, step has failed
        cursorQueue.task_done()
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","runQueue: Queue job failed: ", job, " error: ",e)
        print(datetime.datetime.now()," - ERROR - ","Queue job failed: ", job, " error: ",e, file = log)
        exitCode = 1
    return exitCode
    
def runThreads(step, cursorQueue):
    try:
        exitCode = 0
        for thid in range(cursorQueue.qsize()):
            th = Thread(target=runQueue, args=(step, cursorQueue,))
            th.setDaemon(True)
            th.start()
        cursorQueue.join()
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","Threads failed with error: ",e)
        exitCode = -1
    return exitCode

def runStep(task, step, branch):
    global config
    try:
        exitCode, stepStartDate = 0, datetime.datetime.now()
        # print(datetime.datetime.now()," - INFO - ","runStep for step:  ", step.stepName ," THREAD: ",step.thread, " ; CURSOR_LIST_INDEX: ",step.cursorListIndex, " CURSOR: ", step.cursor ," ACTION: ", step.action)
        print(datetime.datetime.now()," - INFO - ","runStep for step:  ", step.stepName ," THREAD: ",step.thread, " ; CURSOR_LIST_INDEX: ",step.cursorListIndex, " CURSOR: ", step.cursor ," ACTION: ", step.action,file = log)
        cursorQueue = Queue()
        THREAD = int(step.thread) if step.thread.isdigit() else 0
        if isinstance(step.cursor, list) and isinstance(step.cursorListIndex, list):
            thid = 0
            for cur in step.cursor:
                cursorQueue.put("task." + str(task.taskName) + ".step." + str(step.stepName) + ".cur." + str(cur) )
                if THREAD <= thid: 
                    exitCode = thid = runThreads(step, cursorQueue) 
                else: 
                    thid += 1
            if not cursorQueue.empty():
                exitCode = runThreads(step, cursorQueue)
        elif "CONF_NOT_FOUND" not in step.action:
            exitCode = eval(step.action + "(\"" + str(task.taskName) + "\",\"" + str(step.stepName) + "\",\"" + str(cur) + "\")" ) 
        # print(datetime.datetime.now()," - INFO - step:  ", step.stepName , " execution time is: ", datetime.datetime.now() - stepStartDate)
        print(datetime.datetime.now()," - INFO - step:  ", step.stepName , " execution time is: ", datetime.datetime.now() - stepStartDate ,file = log)
        if len(step.cursorFail) != 0:
            print(datetime.datetime.now()," - STEP FAILED - ","Branch:", branch.branchName,", Step:",step.stepName,", Step Description:", step.stepDesc,", Failed Cursors:",step.cursorFail)
            print(datetime.datetime.now()," - STEP FAILED - ","Branch:", branch.branchName,"Step:",step.stepName,", Step description:", step.stepDesc,"Failed Cursors:",step.cursorFail,file=log)
            exitCode = -1
            step.cursor = sorted(set(step.cursorFail)) # only rerun step with failed cursors
            step.failures += 1
            if (step.failures < step.maxFailures):
                step.cursorFail = [] # reset cursorFail to be empty
                time.sleep(step.waittime)
                return runStep(task, step, branch)
    except:
        exitCode = -1
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","Exception occurred in runStep for step:  ", step.stepName , " error: ", e)
        print(datetime.datetime.now()," - ERROR - ","Exception occurred in runStep for step:  ", step.stepName , " error: ", e ,file = log)
    return exitCode 

def getStep(task, branch):
    try:
        exitCode = 0
        step = branch.steps[branch.curStep]
        print(datetime.datetime.now(), " - INFO - ", "Step: " , step.stepName ,  ", where next steps: " , step.success , ", and step description: " , step.stepDesc ,file = log)
        step.cursorFail = [] # reset before running again
        exitCode = runStep(task, step, branch)
                
        if (exitCode != -1) and isinstance(step.success, dict):
            if branch.curStep != branch.lastStep:
                branch.curStep = step.success.values()[0][0]
                if branch.traceBranch:                                      # trace link
                    if branch.curStep == branch.lastFail:                   # remove nextFail loop from links
                        delStep = branch.curStep
                        while delStep != branch.lastFail:
                            delNext = task.links[delStep]
                            del task.links[delStep]
                            delStep = delNext
                    else:
                        if branch.curStep in task.links.keys(): 
                            task.links[branch.curStep].append(step.stepName)
                        else:
                            task.links[branch.curStep] = [step.stepName]
                exitCode = getStep(task, branch)
            else:                                                           # start new branch
                branch.done = True
                if (len(step.success.values()) == 1) and (len(step.success.values()[0]) == 1): # next step is a merge or exit
                    if step.success.values()[0][0] == "exit":
                        return exitCode
                    nextBranchName = step.success.values()[0][0]
                    nextBranch = task.branchesDict[nextBranchName]
                    if branch.traceBranch:                                  # trace next branch
                        nextBranch.traceBranch = True
                        if nextBranchName in task.links.keys(): 
                            task.links[nextBranchName].append(step.stepName)
                        else:
                            task.links[nextBranchName] = [step.stepName]
                    branchReady = True
                    for b in nextBranch.dependencies:
                        brch = task.branchesDict[b]
                        if not brch.done:
                            branchReady = False
                    if branchReady:
                        exitCode = getStep(task, nextBranch)
                elif (len(step.success.values()) > 1) or (len(step.success.values()[0]) > 1): # next step forks
                    branchQueue = Queue()
                    for keyStep in step.success.keys():
                        for forkBranch in step.success[keyStep]:
                            if branch.traceBranch:                                  # trace forked branches
                                task.branchesDict[forkBranch].traceBranch = True
                                if forkBranch in task.links.keys():
                                    task.links[forkBranch].append(step.stepName)
                                else:
                                    task.links[forkBranch] = [step.stepName]
                            branchQueue.put(task.branchesDict[forkBranch])
                    exitCode = forkBranches(task, branchQueue)
        elif exitCode == -1:
            if (step.stepName in branch.failedSteps) or (step.nextFail == "exit"):   # step has failed before (broken link) - traceback
                def traceback(stepName):
                    if stepName in task.links.keys():
                        for name in task.links[stepName]:
                            traceback(name)
                    elif stepName not in task.restart:
                        task.restart.append(stepName)
                traceback(step.stepName)
                return exitCode
            else: # call nextFail step
                nextStep = Step(task, step.nextFail)
                branch.traceBranch = True
                branch.failedSteps.append(step.stepName)
                branch.lastFail = step.stepName
                branch.curStep = nextStep.stepName
                if step.nextFail in task.links.keys():                      # trace link
                    task.links[step.nextFail].append(step.stepName)
                else:
                    task.links[step.nextFail] = [step.stepName]
                while (nextStep.stepName != "exit") and (nextStep.stepName not in branch.steps.keys()) and (nextStep.stepName != branch.lastStep): # add nextFail steps to step list until failBranch merges with original branch or ends
                    if nextStep.curInherit:                                 # set cursor to previous step's cursor if curInherit is True
                        nextStep.cursor = step.cursor
                    branch.steps[nextStep.stepName] = nextStep
                    task.stepObs[nextStep.stepName] = nextStep              # add step object to task
                    next = nextStep.success.values()[0][0]                  # failure branch only a sequence of steps
                    nextStep = Step(task, next)
                if nextStep.stepName == "exit":
                    branch.lastStep = nextStep.stepName                     # reset last step if branch doesn't merge with success branch
                exitCode = getStep(task, branch)                            # call getStep with nextFail as curStep
    except:
        e = sys.exc_info() 
        exitCode = -1
        step = branch.steps[branch.curStep]
        print(datetime.datetime.now(), " - ERROR - ", "Current step: " , step.stepName , "; Next step: ", step.success , "; Step description: " , step.stepDesc , "; with exitCode: ", exitCode, " error: ",e) 
        print(datetime.datetime.now(), " - ERROR - ", "Exception occurred in getStep for Current step: " , step.stepName , "; where next step: ", step.success , \
              "; and step description: " , step.stepDesc , "; with exitCode: ", exitCode, " error: ",e ,file = log)
 
    return exitCode

def runBranchQueue(task, branchQueue):
    global config
    if branchQueue.empty():
        print(datetime.datetime.now(),"runQueue - branchQueue is empty",file = log)
        return -1
    try: 
        exitCode = 0
        branch = branchQueue.get()
        print(datetime.datetime.now()," - INFO - ","Running branchQueue branch: ", branch.branchName, file = log)
        exitCode = getStep(task, branch)
        branchQueue.task_done()
        return exitCode
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","runStepQueue: branchQueue failed: ", branch.branchName, " error: ",e)
        print(datetime.datetime.now()," - ERROR - ","branchQueue failed: ", branch.branchName, " error: ",e, file = log)
        return -1

def forkBranches(task, branchQueue): 
    try:
        exitCode = 0
        for branchId in range(branchQueue.qsize()):
            branch = Thread(target=runBranchQueue, args=(task, branchQueue,))
            branch.setDaemon(True)
            branch.start()
        branchQueue.join()
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","forkBranches: Branches failed with error: ",e)
        print(datetime.datetime.now()," - ERROR - ","Branches failed with error: ",e, file = log)
        exitCode = -1 
    return exitCode

def runTask(task):
    global config
    try:
        exitCode, taskStartDate = 0, datetime.datetime.now()
        # print(datetime.datetime.now()," - INFO - ","runTask for task:  ", task.taskName ," STARTING STEPS: ", task.start)
        print(datetime.datetime.now()," - INFO - ","runTask for task:  ", task.taskName , " STARTING STEPS: ", task.start,file = log)
        if isinstance(task.start, dict):
            for mergeStep in task.start.keys():
                if (len(task.start.values()[0]) > 1):
                    branchQueue = Queue()
                    for branchName in task.start[mergeStep]:
                        branchQueue.put(task.branchesDict[branchName])
                    exitCode = forkBranches(task, branchQueue)
                elif (len(task.start.values()[0]) == 1):
                    branchName = task.start.values()[0][0]
                    branch = task.branchesDict[branchName]
                    exitCode = getStep(task, branch)
        if exitCode is None : exitCode = -1
        print(datetime.datetime.now()," - INFO - task:  ", task.taskName , " execution time is: ", datetime.datetime.now() - taskStartDate ,file = log)
    except:
        exitCode = -1
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","Exception occurred in runTask for task:  ", task.taskName , " error: ", e)
        print(datetime.datetime.now()," - ERROR - ","Exception occurred in runTask for task:  ", task.taskName , " error: ", e ,file = log)
        return exitCode
    return exitCode 

def makeBranches(task, curBranch, step): # when reach mergeStep, stop and then do the mergeStep branch
    try:
        # print("CURSOR: ", step.cursor) # delete
        exitCode = 0
        if (len(step.success.values()) == 1) and (len(step.success.values()[0]) == 1):
            next = step.success.values()[0][0]
            nextStep = Step(task, next)
            if next == "exit":
                task.branchValidDict[curBranch.branchName] = True
                curBranch.lastStep = step.stepName
                return exitCode
            elif next == curBranch.mergeStep: # done creating curBranch; start new branch(es)
                curBranch.lastStep = step.stepName 
                task.branchValidDict[curBranch.branchName] = True
                nextBranch = task.branchesDict[next] # check mergeStep branch dependencies
                mergeReady = True
                for b in nextBranch.dependencies:
                    if not task.branchValidDict[b]:
                        mergeReady = False
                if mergeReady:
                    exitCode = makeBranches(task, nextBranch, nextStep) # start mergeBranch
            else: 
                curBranch.steps[next] = nextStep
                task.stepObs[next] = nextStep # add step object to task
                exitCode = makeBranches(task, curBranch, nextStep)
        elif len(step.success.values()) > 1 or len(step.success.values()[0]) > 1: # create new branches if forking
            task.branchValidDict[curBranch.branchName] = True
            curBranch.lastStep = step.stepName
            for merge in step.success.keys():
                if merge != "0": 
                    mergeStep = Step(task, merge)
                    mergeBranch = Branch(task, merge, "0") # create mergeBranch to track dependencies
                    mergeBranch.steps[merge] = mergeStep
                    task.stepObs[merge] = mergeStep # add step object to task
                    task.branchesDict[merge] = mergeBranch
                    task.branchValidDict[merge] = False
                    for b in step.success[merge]:
                        mergeBranch.dependencies.append(b) # put forked branch names in mergeBranch dependencies
                        task.branchValidDict[b] = False
            for merge in step.success.keys():
                for branchName in step.success[merge]:
                    nextStep = Step(task, branchName)
                    task.stepObs[branchName] = nextStep # add step object to task
                    newBranch = Branch(task, branchName, merge)
                    newBranch.steps[branchName] = nextStep
                    task.branchesDict[branchName] = newBranch
                    exitCode = makeBranches(task, newBranch, nextStep) # create branch for each forked step
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","Exception occurred in makeBranches for task:  ", task.taskName , step.stepName, " error: ", e )
        print(datetime.datetime.now()," - ERROR - ","Exception occurred in makeBranches for task:  ", task.taskName , " error: ", e ,file = log)
        exitCode = -1
    return exitCode

def getTask(task):
    global config 
    try:
        # print("getTask taskName: ", task.taskName) # delete
        exitCode = task.taskName
        if isinstance(task.start, dict) and (task.taskName != "start") and (task.taskName != "exit"): # validate task and create branchesDict
            if len(task.start.values()) > 1 or len(task.start.values()[0]) > 1: # forking branches
                for merge in task.start.keys():
                    if merge != "0": # if 0, branches don't merge
                        mergeStep = Step(task, merge)
                        mergeBranch = Branch(task, merge, "0")
                        mergeBranch.steps[merge] = mergeStep
                        task.stepObs[merge] = mergeStep # add step object to task
                        task.branchesDict[merge] = mergeBranch
                        task.branchValidDict[merge] = False
                        for b in task.start[merge]:
                            mergeBranch.dependencies.append(b) # put forked branch names in mergeBranch dependencies
                            task.branchValidDict[b] = False
                for mergeStep in task.start.keys():
                    for branchName in task.start[mergeStep]:
                        newBranch = Branch(task, branchName, mergeStep)
                        step = Step(task, branchName)
                        newBranch.steps[branchName] = step
                        task.stepObs[branchName] = step # add step object to task
                        task.branchesDict[branchName] = newBranch
                        exitCode = makeBranches(task, newBranch, step) # create branch for each forked step
            elif (len(task.start.values()) == 1) and (len(task.start.values()[0]) == 1):
                firstStep = task.start.values()[0][0]
                step = Step(task, firstStep)
                branch = Branch(task, firstStep, "0")
                branch.steps[firstStep] = step
                task.stepObs[firstStep] = step # add step object to task
                task.branchesDict[firstStep] = branch
                task.branchValidDict[firstStep] = False
                exitCode = makeBranches(task, branch, step) # create branch for each forked step
        print(datetime.datetime.now(), " - INFO - ", "Task: ", task.taskName ,  ", where next task: " , task.nextTask , ", and task description: " , task.taskDesc ,file = log)
        if (str(task.taskName) == "exit") or ("CONF_NOT_FOUND" in task.taskName):
            exitCode = str(task.taskName)
        else:
            exitCode = runTask(task) 
            # for branch in task.branchesDict.values(): # delete
                # print("branch:", branch.branchName, " steps:", branch.steps.keys(), " last step:", branch.lastStep) # delete
            if (exitCode == "CONF_NOT_FOUND") or (len(task.restart) != 0):
                print(datetime.datetime.now(), " - INFO - ", "Task Failed: ", task.taskName ,", Re-Start at steps: " , task.restart)
                print(datetime.datetime.now(), " - INFO - ", "Task Failed: ", task.taskName ,", Re-Start at steps: " , task.restart, file = log)
                for st in task.restart:
                    print("STEP: ", st, " failed with cursors ", task.stepObs[st].cursor)
                    print("STEP: ", st, " failed with cursors ", task.stepObs[st].cursor, file = log)
                exitCode = getTask(Task(task.nextFail))
            else:
                exitCode = getTask(Task(task.nextTask))
    except:
        e = sys.exc_info() 
        exitCode = -1
        print(datetime.datetime.now(), " - ERROR - ", "Exception occurred in getTask for Current task: " , task.taskName , "; where next task: ", task.nextTask , \
      "; and task description: " , task.taskDesc , "; with exitCode: ", exitCode, " error: ",e )
        print(datetime.datetime.now(), " - ERROR - ", "Exception occurred in getTask for Current task: " , task.taskName , "; where next task: ", task.nextTask , \
      "; and task description: " , task.taskDesc , "; with exitCode: ", exitCode, " error: ",e ,file = log)
    return exitCode

def doTest(configFileName):
    global config
    try:
        print("TestIt is True")
        for testList in getConfig(config,"WORKFLOW.TEST.FUNCTIONS"):
            if "getConfig" in testList: 
                print("getConfig:",getConfig(config,"WORKFLOW.TASKS.task1.STEPS.stepA1.CALL.CURSOR"))
                print("getConfig:",getConfig(config,"WORKFLOW.TASKS.task1.STEPS.stepA1.CALL.CMDLIST"))
                print("TASKS",getConfig(config,"WORKFLOW.TASKS"))
            elif "getTask" in testList: 
                exitCode = initiateLog(str(0))
                print(datetime.datetime.now()," - INFO - ",getConfig(config,"LOGGING.0.NAME") , " started using configuration file - " , configFileName ,file = log)
                task = Task("start") # new Task
                # task = Task(Task("start").nextTask) # start task is just a pointer
                exitCode = getTask(task)
                print(datetime.datetime.now()," - INFO - ",getConfig(config,"LOGGING.0.NAME") , " finished with exitCode: " ,exitCode, "; using configuration file - " , configFileName ,file = log)    
            elif "curPattern" in testList:
                print("curPattern",curPattern("dasdf[%Y]ad[%m]sa[%Y%m]sdf","201405"))
            elif "addTime" in testList:
                print("addTime",addTime("201501", "201505", 2, "m", "%Y%m"))
            elif "getCursor" in testList:
                print("getCursor",getCursor(["200907:201405"],'%Y%m'))
            else:
                print("testList is empty")
        print("Done Testing")
    except:
        raise

class Usage(Exception):
    def __init__(self, msg):
        self.msg = msg

def main(argv=None):
    global config,testIt
    if argv is None:
        argv = sys.argv
    try:   
        print(datetime.datetime.now()," - INFO - ","Configuration file is: " , argv[1])
        configFileName = str(argv[1])   
        configFile = open(configFileName)
        config = json.load(configFile)
        configFile.close()
        config = parseConfig(config)
        exitCode = initiateLog(str(0))
        testIt = True if getConfig(config,"WORKFLOW.TEST.FLAG") == "True" else False
        if testIt: 
            doTest(configFileName)
        elif not testIt:
            try:
                print(datetime.datetime.now(), " - INFO - ","LIST of TASKS",getConfig(config,"WORKFLOW.TASKS","LIST_INDEX"))
                if exitCode == 0:
                    print(datetime.datetime.now()," - INFO - ospid: ",os.getpid(), " logging: " ,getConfig(config,"LOGGING.0.NAME") , " started using configuration file - " , configFileName ,file = log)
                    # # exitCodeRep = inititateRep(batchDateTime)
                    task = Task("start") 
                    exitCode = getTask(task)
                    print(datetime.datetime.now()," - INFO - ospid: ",os.getpid(), " total execution time is: ", datetime.datetime.now() - batchDateTime, " logging: " ,getConfig(config,"LOGGING.0.NAME") , " finished with exitCode: " ,exitCode, "; using configuration file - " , configFileName ,file = log)    
                else:
                    print(datetime.datetime.now(), " - FAILURE - - ospid: ",os.getpid(), " logging: " ,"Logging initialization failed")
            except:
                e = str(sys.exc_info()[0]) + str(sys.exc_info()[1]) + str(sys.exc_info()[2]) 
                # print(datetime.datetime.now(), " - ERROR - - ospid: ",os.getpid(), " total execution time is: ", datetime.datetime.now() - batchDateTime, " Exception occurred in getting task with error: ",e)
                print(datetime.datetime.now(), " - ERROR - - ospid: ",os.getpid(), " total execution time is: ", datetime.datetime.now() - batchDateTime, " Exception occurred in getting task with error: ",e ,file = log)

    except IndexError: 
        configFileName="test.aws.cfg.json"
        print(datetime.datetime.now()," - ERROR - ","Configuration file doesn't defined, will use default: " , configFileName)

    except Usage, err:
        print >>sys.stderr, err.msg
        print >>sys.stderr, "for help use --help"
        return 2

class Task:
    def __init__(self, taskName):
        self.taskName = taskName
        self.taskDesc = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".DESC") 
        self.start = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".START")
        self.steps = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".STEPS")
        self.nextTask = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".NEXT.SUCCESS")
        self.nextFail = getConfig(config,"WORKFLOW.TASKS." + str(taskName) +".NEXT.FAILURE")
        self.branchesDict = {} # maps of branchName to branch object
        self.branchValidDict = {} # for task validating purposes; map branch name to boolean
        self.links = {}
        self.restart = [] # list of failed steps; starting point for re-run
        self.stepObs = {} # maps stepname to step object
    
class Branch:
    def __init__(self, task, curStep, mergeStep):
        self.task = task
        self.branchName = curStep # branchName = first step in  branch
        self.curStep = curStep # curStep name
        self.mergeStep  = mergeStep # 0 if branch not the product of a fork
        self.lastStep = None
        self.steps = {} # map of step names to steps in branch
        self.dependencies = [] # list of branch names
        self.done = False # branch successfully completed
        self.traceBranch = False # if branch needs to be tracked in the case of a failure
        self.failedSteps = []
        self.lastFail = None
    
class Step:
    def __init__(self, task, stepName):
        self.task = task
        self.stepName = stepName
        self.stepDesc = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".DESC") 
        self.success = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.SUCCESS")
        self.nextFail = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.FAILURE.NEXT_STEP")
        self.maxFailures = int(getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.FAILURE.MAX_FAILURES"))
        self.waittime = getWaittime(getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".NEXT.FAILURE.WAITTIME"))
        self.action = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.ACTION")
        self.failures = 0
        self.cursorFail = []

        self.thread = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.THREAD") 
        self.cursor = getCursor(getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.RANGE"), \
                                getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.DATATYPE"), \
                                getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.INCREMENT"), \
                                getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.FORMAT"))
        self.cursorListIndex = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.RANGE", "LIST_INDEX")
        self.curInherit = getConfig(config,"WORKFLOW.TASKS." + str(task.taskName) + ".STEPS." + str(stepName) +".CALL.CURSOR.INHERIT")
        
if __name__ == "__main__":
    sys.exit(main())
