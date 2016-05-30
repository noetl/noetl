"use strict";
var ConfigEntry = require('./ConfigEntry');

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Step class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

const _ancestor      = Symbol("list of incoming steps");
const _child         = Symbol("list of next steps");
const _branch        = Symbol("branch name");
const _status       = "status of step" // [READY||RUNNING||WAITING||FINISHED||FAILED]

/**
 * @class Step
 * @classdesc Workflow Step's handler.
 * @extends Task
 */
module.exports = class Step extends ConfigEntry{
    constructor() {
        super(...arguments);
        this[_ancestor] = new Set();
        this[_child]    = new Set();
        this[_branch]   = undefined;
        this[_status]   = "READY"
         if (arguments[0] === "root") {
            this.NEXT = {"SUCCESS":Object.assign({},arguments[1])};
        }

    }
    static step() {
        return new Step(...arguments)
    }
    set ancestor(...ancestor) {
        this[_ancestor].add(...ancestor);
    }
    set child(...child) {
        this[_child].add(...child);
    }
    set branch(branch) {
        this[_branch] = branch || undefined;
    }
    get ancestor() {
        return this[_ancestor] || undefined;
    }
    get child() {
        return this[_child] || undefined;
    }
    get branch() {
        return this[_branch] || undefined;
    }
    get nextSuccess () {
        return this["NEXT"] || undefined;
    }
    get nextFailure () {
        return this.NEXT.FAILURE || undefined;
    }
    get getCall(){
        return this.CALL || undefined;
    }
    get getCursor (){
        return this.CURSOR || undefined;
    }
    get getAction (){
        return this.ACTION || undefined;
    }

    
};


//export  {Step}