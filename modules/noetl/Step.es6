"use strict";
var Task = require('./Task');

module.exports = class Step extends Task{
    constructor() {
        super(...arguments);
    }
    static step() {
        return new Step(...arguments)
    }
    get call(){
        return this.CALL || undefined;
    }
    get action (){
        return this.ACTION || undefined;
    }
    get cursor (){
        return this.CURSOR || undefined;
    }
};


//export  {Step}