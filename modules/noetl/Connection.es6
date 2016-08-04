/**
 * Created by lakhs on 8/4/2016.
 */


var assert = require('assert');
var SSH = require('ssh2');

module.exports=class Connection {
    constructor(){
        let [cmd,opts]= [arguments[0],arguments[1]]
        this.ssh = new SSH
        this.opts = opts
        this.cmd = cmd
    }
    static getOpts(...arg){
        return (arg[0],arg[1]);
    }
}