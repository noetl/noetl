def getAllCallableMethods(obj):
    callableMethods = [method for method in dir(obj) if callable(getattr(obj, method))]
    return callableMethods
