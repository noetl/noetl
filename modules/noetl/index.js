"use strict";

var _toConsumableArray2 = require('babel-runtime/helpers/toConsumableArray');

var _toConsumableArray3 = _interopRequireDefault(_toConsumableArray2);

var _regenerator = require('babel-runtime/regenerator');

var _regenerator2 = _interopRequireDefault(_regenerator);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

var _marked = [generateTaskList].map(_regenerator2.default.mark);

var fs = require('fs'),
    nconf = require('nconf'),
    co = require('co'),
    ConfigEntryPath = require('./ConfigEntryPath'),
    ConfigEntry = require('./ConfigEntry'),
    Task = require('./Task'),
    Step = require('./Step'),
    count = 0;
require("babel-polyfill");

var PROJECT = 'PROJECT',
    WORKFLOW = 'WORKFLOW',
    TASKS = 'TASKS',
    START = 'start',
    EXIT = 'exit'; //,
//SEP = [' ',':','.',',',';','|','-'];

//Read configuration file
nconf.argv().env().file({ file: '../../conf/coursor.inherit.cfg.v1.json' });

//let WorkflowTasks=new ConfigEntryPath(WORKFLOW,TASKS),
//    WorkflowTasksStart = new ConfigEntryPath('-',WORKFLOW,TASKS,START), WorkflowTasksExit = new ConfigEntryPath(' ',  WORKFLOW,TASKS,EXIT), taskSep= ConfigEntry.validateConfigEntry(new ConfigEntryPath(WORKFLOW,'TASKSEP').configEntryPath);
//
//console.log(`WorkflowTasksStart ${WorkflowTasks.configEntryName} WorkflowTasksStart ${WorkflowTasksStart.configEntryName}`);

//Check if mandatory keys like Workflow Tasks, Project Name, Tasks Starting Entry point and Exit are exists.
//nconf.required([WORKFLOW,TASKS,START, WorkflowTasksStart.configEntryPath, WorkflowTasksExit.configEntryPath]);
nconf.required([WORKFLOW + ':' + TASKS + ':' + START, WORKFLOW + ':' + TASKS + ':' + EXIT]);

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

function generateTaskList(task) {
    var sep = arguments.length <= 1 || arguments[1] === undefined ? '' : arguments[1];
    return _regenerator2.default.wrap(function generateTaskList$(_context) {
        while (1) {
            switch (_context.prev = _context.next) {
                case 0:
                    _context.next = 2;
                    return task;

                case 2:
                    if (!(task._entryPath !== 'exit' && task.nextSuccess)) {
                        _context.next = 4;
                        break;
                    }

                    return _context.delegateYield(generateTaskList(ConfigEntry.configEntry(sep, WORKFLOW, TASKS, task.nextSuccess)), 't0', 4);

                case 4:
                case 'end':
                    return _context.stop();
            }
        }
    }, _marked[0], this);
};

// Initiate a starting task to push workflow

var startTask = new Task('-', WORKFLOW, TASKS, 'start');
//
console.log(count++, "!!!startConfig:", startTask);
console.log(count++, 'startConfig.entryId: ' + startTask.entryId);
console.log(count++, " ,startConfig.entryId", startTask.entryId);
console.log(count++, " ,startConfig.nextSuccess", startTask.nextSuccess);

var tasks = [].concat((0, _toConsumableArray3.default)(generateTaskList(new Task('-', WORKFLOW, TASKS, 'start'), '-')));

console.log("VARTATSKS: ", tasks);

var translatedEntry = ConfigEntry.translateConfigEntryReferences({}, tasks[1].STEPS.step1);
console.log("translatedEntry", translatedEntry);
//
console.log("translatedEntry1", translatedEntry.CALL.EXEC.CMD);

console.log("translatedEntry2", translatedEntry.CALL.EXEC.CMD);

//let tasks = Array.from(WorkflowTasks).

//# sourceMappingURL=index.js.map