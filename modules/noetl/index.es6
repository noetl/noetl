"use strict";
var fs    = require('fs'),
    nconf = require('nconf'),
    co = require('co'),
    ConfigEntry = require('./ConfigEntry'),
    Task = require('./Task'),
    Step = require('./Step'),
    count = 0;
require("babel-polyfill");

const PROJECT = 'PROJECT',
      WORKFLOW = 'WORKFLOW', TASKS = 'TASKS',
      START = 'start', EXIT = 'exit';//,
      //SEP = [' ',':','.',',',';','|','-'];

//Read configuration file
nconf.argv()
    .env()
    .file({ file: '../../conf/coursor.inherit.cfg.v1.json' });


nconf.required([`${WORKFLOW}:${TASKS}:${START}`,`${WORKFLOW}:${TASKS}:${EXIT}`]);


function* generateTaskList(task,sep=''){
    yield task;
    if (task._entryPath !== 'exit' && task.nextSuccess) {
        yield  *generateTaskList(ConfigEntry.configEntry(sep,WORKFLOW,TASKS,task.nextSuccess));
    }
};

// Initiate a starting task to push workflow

let startTask = new Task('-',WORKFLOW,TASKS,'start');
//
console.log(count++,"!!!startConfig:", startTask);
console.log(count++,`startConfig.entryId: ${startTask.entryId}`);
console.log(count++," ,startConfig.entryId",startTask.entryId);
console.log(count++," ,startConfig.nextSuccess",startTask.nextSuccess);

var tasks = [...generateTaskList(new Task('-',WORKFLOW,TASKS,'start'),'-')];

console.log("VARTATSKS: ",tasks);

var translatedEntry = ConfigEntry.translateConfigEntryReference({},tasks[1].STEPS.step1);

console.log("translatedEntry", translatedEntry);

console.log("translatedEntry1",translatedEntry.CALL.EXEC.CMD);


//let tasks = Array.from(WorkflowTasks).


