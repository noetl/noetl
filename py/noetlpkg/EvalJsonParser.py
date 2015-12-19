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
import sys, re, os, json, datetime
from distutils.command.config import config
from EvalJsonParser import *

test = True

def getConfig(cfg, confRequest, confCase=None):
    global log
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

def parseConfig(configFile):
    global config
    try:
        config = configFile
        return stripJsonLayer(config)
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","getJsonString failed with error: ",e)

# peels of layers of config file until reaches a string
def stripJsonLayer(cfg):
    try:
        if isinstance(cfg, dict):
            for key, val in cfg.iteritems():
                cfg[key] = stripJsonLayer(val)
        elif isinstance(cfg, list): 
            for id, element in enumerate(cfg):
                cfg[id] = stripJsonLayer(element)
        elif isinstance(cfg, basestring):
            cfg = getJsonString(str(cfg))
        return cfg
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","stripJsonLayer failed with error: ",e)

# splits variable path to get the individual labels
def getJsonPath(jsonPath):
    try: 
        jsonList = jsonPath.split(".")
        return checkJsonType(config, jsonList)
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","getJsonPath failed with error: ",e)

# finds and returns the value to the key matching the label in the jsonMap
def getJsonMap(jsonMap, jsonLabel):
    try: 
        for key, val in jsonMap.iteritems():
            if str(key) in jsonLabel:
                if isinstance(val, basestring):
                    return getJsonString(str(val))
                return val
        return "Unknown Key"
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","getJsonMap failed with error: ",e)

def getJsonList(jsonList, jsonLabel):
    try:
        if not isinstance(jsonLabel, unicode):
            jsonLabel = unicode(jsonLabel, 'utf-8')
        if jsonLabel.isnumeric():
            i = int(jsonLabel)
            return jsonList[i]
        else:
            listCopy = []
            for i in range(len(jsonList)):
                if isinstance(jsonList[i], basestring):
                    element = getJsonString(str(jsonList[i]))
                    listCopy.append(element)
                else:
                    listCopy.append(jsonList[i])
            return listCopy
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","getJsonList failed with error: ",e)

# finds all variables in a string and replaces them with their respective values
def getJsonString(jsonStr):
    try:
        pattern = re.compile('.*?\${(.*?)\}.*?')
        varList=pattern.findall(jsonStr)
        if len(varList) != 0:
            for id, var in enumerate(varList):
                replaceVal = str(getJsonPath(var))
                jsonStr = jsonStr.replace( "${"  + varList[id] + "}" , replaceVal )
        return jsonStr
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","getJsonString failed with error: ",e)

# finds and returns the corresponding configuration to each label
def checkJsonType(cfg, path):
    try: 
        for label in path:
            if isinstance(cfg, dict):
                cfg = getJsonMap(cfg, label)
            if isinstance(cfg, list):
                cfg = getJsonList(cfg, label)
        if isinstance(cfg, basestring):
            return getJsonString(str(cfg))
        return cfg
    except:
        e = sys.exc_info() 
        print(datetime.datetime.now()," - ERROR - ","checkJsonType failed with error: ",e)

def println(test, *argv):
    if test:
        print(*argv)

class Usage(Exception):
    def __init__(self, msg):
        self.msg = msg

def main(argv=None):
    # global config
    if argv is None:
        argv = sys.argv
    try:
        configFileName = str(argv[1])   
        configFile = open(configFileName)
        config = json.load(configFile)
        configFile.close()
        
        # config = stripJsonLayer(config)
        config = parseConfig(config)
        print(config)

    except Usage, err:
        print >>sys.stderr, err.msg
        print >>sys.stderr, "for help use --help"
        return 2

if __name__ == "__main__":
    sys.exit(main())
