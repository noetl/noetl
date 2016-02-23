def getAllCallableMethods(obj):
    callableMethods = [method for method in dir(obj) if
                       callable(getattr(obj, method)) and not method.startswith("_" + obj.__class__.__name__)]
    return callableMethods
