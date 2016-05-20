"use strict";
var fs    = require('fs'),
    nconf = require('nconf'),
    co = require('co'),
    ConfigEntryPath = require('./ConfigEntryPath'),
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


//let WorkflowTasks=new ConfigEntryPath(WORKFLOW,TASKS),
//    WorkflowTasksStart = new ConfigEntryPath('-',WORKFLOW,TASKS,START), WorkflowTasksExit = new ConfigEntryPath(' ',  WORKFLOW,TASKS,EXIT), taskSep= ConfigEntry.validateConfigEntry(new ConfigEntryPath(WORKFLOW,'TASKSEP').configEntryPath);
//
//console.log(`WorkflowTasksStart ${WorkflowTasks.configEntryName} WorkflowTasksStart ${WorkflowTasksStart.configEntryName}`);

//Check if mandatory keys like Workflow Tasks, Project Name, Tasks Starting Entry point and Exit are exists.
//nconf.required([WORKFLOW,TASKS,START, WorkflowTasksStart.configEntryPath, WorkflowTasksExit.configEntryPath]);
nconf.required([`${WORKFLOW}:${TASKS}:${START}`,`${WORKFLOW}:${TASKS}:${EXIT}`]);

//let test = new Task(new ConfigEntryPath(WORKFLOW,TASKS,START));
//
//console.log("test",test);

//function* generateTaskList(taskPath,stopTaskPath,sep='-'){
//    let task = new Task(taskPath);
//    yield task;
//    if (task._entryPath !== stopTaskPath.configEntryPath && task.nextSuccess) {
//        yield  *generateTaskList(ConfigEntryPath.configEntryPath(sep,WORKFLOW,TASKS,task.nextSuccess),stopTaskPath,sep);
//    }
//};

//var tasks = [...generateTaskList(('-',WORKFLOW,TASKS,START),(' ',  WORKFLOW,TASKS,EXIT))];

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

var translatedEntry = ConfigEntry.translateConfigEntryReferences({},tasks[1].STEPS.step1);
console.log("translatedEntry", translatedEntry);
//
console.log("translatedEntry1",translatedEntry.CALL.EXEC.CMD);

console.log("translatedEntry2",translatedEntry.CALL.EXEC.CMD);

//let tasks = Array.from(WorkflowTasks).


