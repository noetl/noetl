"use strict";
var ConfigEntry = require('./ConfigEntry');

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Step class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

const   _ancestor      = Symbol("incoming steps"),
        _child         = Symbol("next steps"),
        _branch        = Symbol("branch name"),
        _status        = "step status"; // [READY||RUNNING||WAITING||FINISHED||FAILED]

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
    getAction (){
        return this.ACTION || undefined
    }


    /**
     * toDate function returns date object from a given string format.
     * @param dt
     * @param format
     * Date format options are:
     * [%m || MM]	Numeric month as a zero-padded decimal number.	01, 02, ..., 12
     * [%y || YY]	Last two digit of the year without century as a zero-padded decimal number.	00, 01, ..., 99
     * [%Y || YYYY]	4 digit year with century as a decimal number.	1970, 1988, 2001, 2013
     * [%H || HH24]	Hour of day (24-hour clock) as a zero-padded decimal number.	(00-23)
     * [%M || MI]	Minute as a zero-padded decimal number.	(00-59)
     * ]%S || SS]	Second as a zero-padded decimal number.	(00-59)
     * @returns {date}
     */
    static toDate(dt, format) {
        let date = new Date(1970, 1, 1)
        let regexp = /(%Y|YYYY)|(%y|YY)|(%d|DD)|(%m|MM)|(%H|HH24)|(%M|MI)|(%S|SS)/g;
        let match, startPos = 0, prevMatchLastIndex = 0,len = 0;
        while (match = regexp.exec(format)) {
            startPos = startPos + match.index - prevMatchLastIndex;
            len = (/(%Y|YYYY)/.test(match[0])) ? 4 : 2;
            switch (match[0]) {
                case "%Y":
                case "YYYY":
                    date.setFullYear(parseInt(dt.substr(startPos,len)));
                    break;
                case "%y":
                case "YY":
                    date.setYear(parseInt(dt.substr(startPos,len)));
                    break;
                case "%m":
                case "MM":
                    date.setMonth(parseInt(dt.substr(startPos,len))-1);
                    break;
                case "%d":
                case "DD":
                    date.setDate(parseInt(dt.substr(startPos,len)));
                    break;
                case "%H":
                case "HH24":
                    date.setUTCHours(parseInt(dt.substr(startPos,len)));
                    break;
                case "%M":
                case "MI":
                    date.setMinutes(parseInt(dt.substr(startPos,len)));
                    break;
                case "%S":
                case "SS":
                    date.setMinutes(parseInt(dt.substr(startPos,len)));
                    break;
                default:
                    throw new Error("toDate failed to match format");
            }
            startPos = startPos + len;
            prevMatchLastIndex = regexp.lastIndex;
        }
        return date
    }

};


//export  {Step}