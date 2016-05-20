"use strict";
var ConfigEntry = require('./ConfigEntry');

module.exports = class Task extends ConfigEntry{
    constructor() {
        console.log("arguments: ",...arguments);
        super(...arguments);
    }
    static task() {
        return new Task(...arguments)
    }
    get nextSuccess (){
        return this.NEXT.SUCCESS || undefined;
    }
    get nextFailure (){
        return this.NEXT.FAILURE || undefined;
    }
    get start (){
        return this.START || undefined;
    }
    generateBranches(){
        {""}
    }
};

//export {Task}