"use strict";
var ConfigEntry = require('./ConfigEntry'),
    Step = require('./Step'),
    keys = Object.keys;

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Task class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////



const _steps        = Symbol("steps");
const _getStepsRoot = Symbol("retrieve the starting reference form task START");
const _root         = "root"; // root is not a step, but just a forkable entry point for the steps.

/**
 * @class
 * @classdesc Workflow Task's handler.
 * @extends ConfigEntry
 */
module.exports = class Task extends ConfigEntry{
    constructor() {
        super(...arguments)
        this[_steps] = new Map()
        this[_getStepsRoot] = () => { return this.START || undefined}
        if (keys(this[_getStepsRoot] () ).length > 0) {
            this[_steps].set(_root, new Step(_root, this[_getStepsRoot]() ) )
            console.log("this[_steps]", this[_steps])
        }
        console.log("entryId", this.entryPath)
        let entryPathList = this.entryPath.split(':');
        if (keys(this.STEPS).length > 0) {
            keys(this.STEPS).forEach(key => {console.log("Task key: ", key); this[_steps].set(key,new Step(...entryPathList,"STEPS",key))});
            keys(this[_steps]).forEach(key => {
                let nextStep = this[_steps].get(key);
                console.log("this[_steps].get(key).nextSuccess(): ",nextStep)
            });
        }
        if(this[_steps].size - 1 > 0 && (keys(this.STEPS).length === this[_steps].size - 1)) {

        }
        console.log("this[_steps]: ", this[_steps])
    }

    static task () {
        return new Task(...arguments)
    }
    get nextSuccess () {
        return this.NEXT.SUCCESS || undefined;
    }
    get nextFailure () {
        return this.NEXT.FAILURE || undefined;
    }
    *defineDependences (step,branch) {
        let done = new Map();
        for (let from of this[_steps].keys()) {
            done.set(from, new Set());
            for (let to of this[_steps].get(from).keys()) {
                if (this.hasStep(from, to) && !done.get(from).has(to)) {
                    done.get(from).add(to);
                    yield [from, to, this[_steps].get(from).get(to)];
                }
            }
        }
    }




};

//export {Task}
