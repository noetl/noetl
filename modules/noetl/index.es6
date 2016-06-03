"use strict";

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL /////////////////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

// for cursor npm install date_format --save https://www.npmjs.com/package/date_format

/**
 * NoETL module dependencies
 */
//require("babel-polyfill");

var fs          = require('fs'),
    nconf       = require('nconf'),
    co          = require('co'),
    ConfigEntry = require('./ConfigEntry'),
    Task        = require('./Task'),
    Step        = require('./Step');

var keys = Object.keys;
var assign = Object.assign;

// Config keys
const   PROJECT     = 'PROJECT',
        WORKFLOW    = 'WORKFLOW',
        TASKS       = 'TASKS',
        START       = 'start',
        EXIT        = 'exit'; //SEP = [' ',':','.',',',';','|','-'];

// Read configuration file
nconf.argv()
    .env()
    .file({ file: '../../conf/coursor.inherit.cfg.v2.json' });

// Validate config file for main entries
nconf.required([`${WORKFLOW}:${TASKS}:${START}`,`${WORKFLOW}:${TASKS}:${EXIT}`]);

/**
 * @function generateTaskList
 * Iterate over all tasks of workflow.
 * @returns { Iterator.<Task> }
 * @example
 * var tasks = [...generateTaskList(new Task('-',WORKFLOW,TASKS,'start'),'-')];
 */
function* generateTaskList(task,sep='-'){
    yield task;
    if (!['exit'].find(x => x === task.entryPath) && task.nextSuccess) {
        yield  *generateTaskList(Task.task(sep,WORKFLOW,TASKS,task.nextSuccess));
    }
};

// Initiate a task list to push workflow
var tasks = [...generateTaskList(new Task('-',WORKFLOW,TASKS,'start'),'-')];


var testCoursor = tasks[1].getStep('step2').getCursor();

console.log("testCoursor",testCoursor)

let testdate = testCoursor.RANGE;





//var str = "-2011-10-31";
//
//
//
//console.log("ddd ",Step.toDate(str,'-YYYY-%m-%d'))


