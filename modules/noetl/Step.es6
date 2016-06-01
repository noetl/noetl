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

};


//export  {Step}