import json
import re
from CommonPrinter import *


class NOETLJsonParser:
    def __init__(self, confPath):
        self.config = None
        self.confFilePath = confPath

    def getConfig(self):
        if self.config is None:
            self.__parseConfig()
        return self.config

    def __parseConfig(self):
        try:
            with open(self.confFilePath) as f:
                # TODO: This doesn't enforce unique step names in the task
                self.config = json.load(f)
                self.__dereferenceConfig(self.config)
        except:
            printer.err(str.format("Parsing configuration file `{0}` failed.", self.confFilePath))
            sys.exit(1)
        printer.info("Successfully parsed configuration file '{0}'.".format(self.confFilePath))

    def __dereferenceConfig(self, config):
        if isinstance(config, dict):
            for key, val in config.iteritems():
                config[key] = self.__dereferenceConfig(val)
        elif isinstance(config, list):
            for id, element in enumerate(config):
                config[id] = self.__dereferenceConfig(element)
        elif isinstance(config, basestring):
            config = self.__getDereferencedString(config)
        else:
            raise RuntimeError("Unknown/Unexpected configuration type")
        return config

    def __getDereferencedString(self, jsonStr):
        varList = NOETLJsonParser.getCurlyBraceReferences(jsonStr)
        if len(varList) != 0:
            for id, var in enumerate(varList):
                replaceVal = str(self.__getReplacedString(var))
                jsonStr = jsonStr.replace("${" + varList[id] + "}", replaceVal)
        return jsonStr

    def __getReplacedString(self, jsonPath):
        jsonList = jsonPath.split(".")
        config = self.config
        for label in jsonList:
            if isinstance(config, dict):
                config = self.__getJsonMap(config, label)
            elif isinstance(config, list):
                config = self.__getJsonList(config, label)
        if isinstance(config, basestring):
            return self.__getDereferencedString(str(config))
        return config

    def __getJsonMap(self, confMap, jsonLabel):
        for key, val in confMap.iteritems():
            if str(key) in jsonLabel:
                if isinstance(val, basestring):
                    return self.__getDereferencedString(str(val))
                return val
        raise RuntimeError("__getJsonMap: Failed to get value for " + str(jsonLabel))

    def __getJsonList(self, listConf, jsonLabel):
        if not isinstance(jsonLabel, unicode):
            jsonLabel = unicode(jsonLabel, 'utf-8')
        if jsonLabel.isnumeric():
            i = int(jsonLabel)
            return listConf[i]
        else:
            listCopy = []
            for i in range(len(listConf)):
                if isinstance(listConf[i], basestring):
                    listCopy.append(self.__getDereferencedString(str(listConf[i])))
                else:
                    listCopy.append(listConf[i])
            return listCopy

    @staticmethod
    def getCurlyBraceReferences(jsonValue):
        pattern = re.compile(".*?\${(.*?)\}.*?")
        return pattern.findall(jsonValue)
