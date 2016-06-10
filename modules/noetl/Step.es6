"use strict";
var ConfigEntry = require('./ConfigEntry');

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Step class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

const   _ancestor           = Symbol("incoming steps"),
        _child              = Symbol("next steps"),
        _branch             = Symbol("branch name"),
        _generateCursorCall = Symbol("cursor items"),
        _generateAction     = Symbol("action items"),
        _status             = "step status"; // [READY||RUNNING||WAITING||FINISHED||FAILED]

/**
 * @class Step
 * @classdesc Workflow Step's handler.
 * @extends ConfigEntry
 */
module.exports = class Step extends ConfigEntry{
    constructor() {
        super(...arguments);
        this[_ancestor] = new Set()
        this[_child]    = new Set()
        this[_branch]   = "0"
        this[_status]   = undefined
         if (arguments[0] === "root") {
            this.NEXT = {"SUCCESS":Object.assign({},arguments[1])}
        }

    }
    // returns a cursor values, have to return execution
    [Symbol.iterator]() { return this[_generateCursorCall](this.getCursorRange(), this.getCursorDataType()) }

    static step() {
        return new Step(...arguments)
    }
    setAncestor(...ancestor) {
        ancestor.forEach((item) => this[_ancestor].add(item))
    }
    setChild(...child) {
        child.forEach((item) => this[_child].add(item))
    }
    setBranch(branch) {
        this[_branch] = branch
    }
    getAncestor () {
        return this[_ancestor] || undefined
    }
    getChild () {
        return this[_child] || undefined
    }
    getBranch () {
        return this[_branch] || undefined
    }
    get nextSuccess () {
        return this.NEXT.SUCCESS || undefined
    }
    get nextFailure () {
        return this.NEXT.FAILURE || undefined
    }
    getCall(){
        return this.CALL || undefined
    }
    getCursor (){
        return this.CALL.CURSOR || undefined
    }
    getCursorRange(){
        return this.getCursor().RANGE || undefined
    }
    getCursorDataType(){
        return this.getCursor().DATATYPE || undefined
    }
    getAction (){
        return this.getCall().ACTION || undefined
    }
    getThread (){
        return this.getCall().THREAD || undefined
    }
    getExec (){
        return this.getCall().EXEC || undefined
    }
    getExecUrl (){
        return this.getExec().URL || undefined
    }
    getExecCmd (){
        return this.getExec().CMD || undefined
    }

    [_generateAction](cur,dataType) {
         let execCmd = this.getExecCmd().map((item) => {
             return item.join().replace(/\[([^\]]+)\]/g, (match, p1) => {
                return  (dataType === "date") ?  ConfigEntry.formatDate(cur, match) : cur })
         })
        return Object.assign({}, {action: this.getAction(), thread: this.getThread(), url: this.getExecUrl(),  cmd: execCmd });
    }

    * [_generateCursorCall](cursorRange, dataType = "integer", increment = 0, end = null) {
        if (Array.isArray(cursorRange)) {
            for (let cur of cursorRange) {
                yield *this[_generateCursorCall](cur, dataType, increment, end)
            }
        } else {
            let from,to = end;
            if(ConfigEntry.isObject(cursorRange)) {
                let {FROM, TO, INCREMENT} = cursorRange;
                from = (dataType === "date" ) ? ConfigEntry.toDate(FROM) : FROM, to =  (dataType === "date" ) ? ConfigEntry.toDate(TO)  : TO, increment = INCREMENT;
            } else if (dataType === "date" ) {
                from = ConfigEntry.isDate(cursorRange) ? new Date(cursorRange.getTime()) : ConfigEntry.toDate(cursorRange)
            } else {
                from = cursorRange
            }
            yield this[_generateAction](from,dataType);
            if (from < to) {
                let nextVal;
                if (from instanceof Date) {
                    nextVal = new Date(from.getTime());
                    let matchResult = increment.toString().match(/(Y)|(M)|(D)/i);
                    switch (matchResult[0].toLowerCase()) {
                        case "y":
                            nextVal.setFullYear(nextVal.getFullYear() + parseInt(increment))
                            break;
                        case "m":
                            nextVal.setMonth(nextVal.getMonth() + parseInt(increment))
                            break;
                        case "d":
                            nextVal.setDate(nextVal.getDate() + parseInt(increment))
                            break;
                        default:
                            nextVal.setDate(nextVal.getDate() + parseInt(increment))
                    }

                } else {
                    nextVal =  from + parseInt(increment);
                }
                yield  *this[_generateCursorCall]((nextVal<=to) ? nextVal : to, dataType, increment, to );
            }
        }
    }



};

//export  {Step}