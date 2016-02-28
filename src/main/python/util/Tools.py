import os

from CommonPrinter import *

REQUEST_FAILED = "CONF_NOT_FOUND"


def processConfRequest(cfg, confRequest):
    try:
        confList = confRequest.split(".")
        for label in confList:
            if isinstance(cfg, dict):
                cfg = cfg.get(label)
                if cfg is None:
                    printer.printInfo("FAILURE: The configuration request failed for '{0}'".format(confRequest))
                    os._exit(1)
            elif isinstance(cfg, list):
                if not isinstance(label, unicode):
                    label = unicode(label, 'utf-8')
                if label.isnumeric():
                    i = int(label)
                    cfg = cfg[i]
                else:
                    raise RuntimeError()
            else:
                raise RuntimeError(str.format('Unknown config object type for "{0}".', cfg))
        return cfg
    except:
        printer.printErr("Fail to process the configuration request: " + confRequest)


def getWaitTime(waitTime):
    try:
        measure = waitTime[- 1].lower()
        timeLength = int(waitTime[:-1])
        if measure == 's':
            return timeLength
        if measure == 'm':
            return timeLength * 60
        if measure == 'h':
            return timeLength * 3600
    except:
        printer.printErr("getWaitTime failed for " + waitTime)


def getCursor(cursorRangeList, dataType, increment, dateFormat):
    try:
        cursor = set()
        for curId, curVal in enumerate(cursorRangeList):
            if ":" in curVal:
                curList = curVal.split(":")
                if len(curList) == 2:
                    cursor.add(curList[0])
                    if dataType.lower() == "date":
                        startDate = stringToDate(curList[0], dateFormat)
                        endDate = stringToDate(curList[1], dateFormat)
                        expanded = __addTime(startDate, endDate, int(increment[:-1]), increment[-1], dateFormat)
                        for cur in expanded:
                            cursor.add(cur)
                    elif dataType.lower() == "integer":
                        increment = int(increment)
                        i = int(curList[0]) + increment
                        while i < (int(curList[1]) + 1):
                            cursor.add(str(i))
                            i += increment
                    else:
                        raise RuntimeError('Wrong data type. It can only be "date" or "integer".')
                else:
                    raise RuntimeError(str.format('Wrong range string "{0}". It should only have one colon.', curVal))
            else:
                cursor.add(curVal)
        return sorted(cursor)
    except:
        printer.printErr(str.format("Failed to construct cursor for `Range:{0},DateType:{1},Format:{2},Increment:{3}`",
                            cursorRangeList, dataType, dateFormat, increment))
        sys.exit(1)


def stringToDate(dateString, dateFormat):
    return datetime.datetime.strptime(dateString.strip(), dateFormat.strip())


def __addTime(startDate, endDate, increment, incType, dateFormat):
    incType = incType.lower()
    currentCursor = []
    timeDelta = datetime.timedelta(days=increment)
    while startDate <= endDate - timeDelta:
        currentCursor.append(startDate.strftime(dateFormat))
        if incType == 'y':
            startDate = datetime.datetime(startDate.year + increment, startDate.month, startDate.day)
        elif incType == 'm':
            startDate = datetime.datetime(startDate.year + ((startDate.month + increment - 1) // 12),
                                          ((startDate.month + increment - 1) % 12) + 1, startDate.day)
        elif incType == 'd':
            startDate = startDate + timeDelta
        else:
            raise RuntimeError("Wrong date increment type. It can only be Y, M or D")
    return currentCursor
