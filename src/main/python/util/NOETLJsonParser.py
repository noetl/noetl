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
                self.config = json.load(f)
                self.__dereferenceConfig(self.config)
        except:
            printErr(str.format("Parsing configuration file `{0}` failed.", self.confFilePath))
            sys.exit(1)
        printInfo("Successfully parsed configuration file '{0}'.".format(self.confFilePath))

    def __dereferenceConfig(self, config):
        if isinstance(config, dict):
            for key, val in config.iteritems():
                config[key] = self.__dereferenceConfig(val)
        elif isinstance(config, list):
            for id, element in enumerate(config):
                config[id] = self.__dereferenceConfig(element)
        elif isinstance(config, basestring):
            config = self.__getDereferencedString(self.config, config)
        else:
            raise RuntimeError("Unknown/Unexpected configuration type")
        return config

    @staticmethod
    def __getDereferencedString(config, jsonStr):
        varList = NOETLJsonParser.getCurlyBraceReferences(jsonStr)
        if len(varList) != 0:
            for id, var in enumerate(varList):
                replaceVal = str(NOETLJsonParser.__getReplacedString(config, var))
                jsonStr = jsonStr.replace("${" + varList[id] + "}", replaceVal)
        return jsonStr

    @staticmethod
    def __getReplacedString(config, jsonPath):
        jsonList = jsonPath.split(".")
        for label in jsonList:
            config = config.get(label)
            if config is None:
                raise RuntimeError(
                    "Dereferencing failed for ${{{0}}}. The property {1} doesn't exist.".format(str(jsonPath), label))
        return config

    @staticmethod
    def getCurlyBraceReferences(jsonValue):
        pattern = re.compile(".*?\${(.*?)\}.*?")
        return pattern.findall(jsonValue)
