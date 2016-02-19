import sys, re, os, json, datetime


class Usage(Exception):
    def __init__(self, msg):
        self.msg = msg


class EvalJsonParser:
    def __init__(self, confPath):
        self.cfg = None
        self.confPath = confPath

    def getConfig(self):
        if self.cfg == None:
            self.parseConfig()
        return self.cfg

    def parseConfig(self):
        try:
            with open(self.confPath) as f:
                config = json.load(f)
                if isinstance(config, dict):
                    pass
                elif isinstance(config, list):
                    pass
                elif isinstance(config, basestring):
                    pass

                print(config)
        except Usage, err:
            print >> sys.stderr, err.msg
            print >> sys.stderr, "for help use --help"
            return 2

