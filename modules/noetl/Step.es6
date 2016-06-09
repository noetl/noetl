"use strict";
var ConfigEntry = require('./ConfigEntry');

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Step class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

const   _ancestor           = Symbol("incoming steps"),
        _child              = Symbol("next steps"),
        _branch             = Symbol("branch name"),
        _generateCursorCall = Symbol("cursor items"),
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
    [Symbol.iterator]() { return this[_generateCursorCall](this.getCursorRange(), this.getCursorIncrement(), this.getCursorDataType()) }

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
    getCursorIncrement(){
        return this.getCursor().INCREMENT || undefined
    }
    getAction (){
        return this.ACTION || undefined
    }

    * [_generateCursorCall](cursorRange, increment = 0, dataType = "integer", end = null) {
        if (Array.isArray(cursorRange)) {
            for (let cur of cursorRange) {
                yield *this[_generateCursorCall](cur, increment, dataType, end)
            }
        } else {
            let from,to = end;
            if(ConfigEntry.isObject(cursorRange)) {
                let {from: start,to: stop} = cursorRange;
                from = (dataType === "date" ) ? ConfigEntry.toDate(start) : start, to =  (dataType === "date" ) ? ConfigEntry.toDate(stop)  : stop;
            } else if (dataType === "date" ) {
                from = ConfigEntry.isDate(cursorRange) ? new Date(cursorRange.getTime()) : ConfigEntry.toDate(cursorRange)
            } else {
                from = cursorRange
            }
            yield from;
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
                yield  *this[_generateCursorCall](nextVal, increment, dataType, to );
            }
        }
    }



};

//export  {Step}