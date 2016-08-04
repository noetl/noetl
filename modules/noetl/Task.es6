"use strict";
var ConfigEntry = require('./ConfigEntry.es6'),
    Step = require('./Step.es6'),
    keys = Object.keys;

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Task class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////



const   _getStepsRoot = Symbol("steps start reference"),
        _steps        = Symbol("steps");

const   ROOT         =  "root", // root is not a step, but just a forkable entry point for the steps.
        STEPS         = "STEPS",
        START         = "START",
        NEXT          = "NEXT";

/**
 * @class
 * @classdesc Workflow Task's handler.
 * @extends ConfigEntry
 */

module.exports = class Task extends ConfigEntry{
    constructor() {
        super(...arguments)
        this[_steps] = new Map()
        this[_getStepsRoot] = () => { return this[START] || undefined}
        try {
            if (keys(this[_getStepsRoot] () ).length > 0) {
                this[_steps].set(ROOT, new Step(ROOT, this[_getStepsRoot]()))
                let entryPathList = this.entryPath.split(':');
                keys(this[STEPS]).forEach(key => {
                    this[_steps].set(key, new Step(...entryPathList, STEPS, key))
                });
                for (let entry of this[_steps]) {
                    let stepName = entry[0], step = entry[1], nextSuccessSteps = step.nextSuccess;
                    keys(nextSuccessSteps).forEach(key => {
                        this[_steps].get(stepName).setChild(...nextSuccessSteps[key])
                        nextSuccessSteps[key].forEach((item) => {
                            this[_steps].get(item).setAncestor(stepName)
                            this[_steps].get(item).setBranch(['0', ''].find(x => x === key) ? item : key)
                        })
                    })
                }
            } else {
                throw new Error("steps starting entry point doesn't exists");
            }
        } catch (e) {
                console.warn(`Steps initializing warning "${e.message}" for ${this.entryPath}`);
        } finally {
                console.log(`Task: ${this.entryPath}`)
                this[_steps].forEach(function(step, stepName) {
                    console.log(`Step -> ${stepName}; ancestors ->  ${Array.from(step.getAncestor()).join(',')}; followers -> ${Array.from(step.getChild()).join(',')}`);
                })
        }
    }

    static task () {
        return new Task(...arguments)
    }

    get nextSuccess () {
        return this[NEXT].SUCCESS || undefined;
    }

    get nextFailure () {
        return this[NEXT].FAILURE || undefined;
    }

    getStep(stepName) {
        return this[_steps].get(stepName);
    }
};

//export {Task}
