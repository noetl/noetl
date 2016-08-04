/**
 * Created by lakhs on 8/4/2016.
 */
var assert = require('assert');
var SSH = require('ssh2');

var Connection = require("./Connection.es6")
module.exports=class RunShell extends Connection {
    constructor() {
        super(...arguments);
        var ssh=this.ssh;
        let cmd,opts;
        cmd=this.cmd;
        opts = this.opts || {};
        opts.port = opts.port || 22;
        assert(opts.user, '.user required');
        opts.privateKey = opts.key;
        opts.username = opts.user;
        //ssh.connect(opts);
        //ssh.exec(cmd, {ssh: ssh})
        RunShell.conection(opts,ssh)
        RunShell.execute(cmd,ssh)
        return ssh;
    }
    static conection(opts,ssh){
        ssh.connect(opts)
        //console.log(opts)
    }
    static execute(cmd,ssh){
        ssh.exec(cmd, {ssh: ssh})
        //console.log(cmd)
    }
}