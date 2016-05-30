"use strict";

<<<<<<< HEAD
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL /////////////////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

/**
 * NoETL module dependencies
 */

=======
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4
var _toConsumableArray2 = require('babel-runtime/helpers/toConsumableArray');

var _toConsumableArray3 = _interopRequireDefault(_toConsumableArray2);

var _regenerator = require('babel-runtime/regenerator');

var _regenerator2 = _interopRequireDefault(_regenerator);

<<<<<<< HEAD
var _assign = require('babel-runtime/core-js/object/assign');

var _assign2 = _interopRequireDefault(_assign);

var _keys = require('babel-runtime/core-js/object/keys');

var _keys2 = _interopRequireDefault(_keys);

=======
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4
function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

var _marked = [generateTaskList].map(_regenerator2.default.mark);

var fs = require('fs'),
    nconf = require('nconf'),
    co = require('co'),
    ConfigEntry = require('./ConfigEntry'),
    Task = require('./Task'),
    Step = require('./Step'),
    count = 0;
require("babel-polyfill");

<<<<<<< HEAD
var keys = _keys2.default;
var assign = _assign2.default;

// Config keys
=======
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4
var PROJECT = 'PROJECT',
    WORKFLOW = 'WORKFLOW',
    TASKS = 'TASKS',
    START = 'start',
    EXIT = 'exit'; //,
//SEP = [' ',':','.',',',';','|','-'];

<<<<<<< HEAD
// Read configuration file
nconf.argv().env().file({ file: '../../conf/coursor.inherit.cfg.v2.json' });

// Validate config file for main entries
nconf.required([WORKFLOW + ':' + TASKS + ':' + START, WORKFLOW + ':' + TASKS + ':' + EXIT]);

/**
 * @function generateTaskList
 * Iterate over all tasks of workflow.
 * @returns { Iterator.<Task> }
 * @example
 * var tasks = [...generateTaskList(new Task('-',WORKFLOW,TASKS,'start'),'-')];
 */
function generateTaskList(task) {
    var sep = arguments.length <= 1 || arguments[1] === undefined ? '-' : arguments[1];
=======
//Read configuration file
nconf.argv().env().file({ file: '../../conf/coursor.inherit.cfg.v1.json' });

nconf.required([WORKFLOW + ':' + TASKS + ':' + START, WORKFLOW + ':' + TASKS + ':' + EXIT]);

function generateTaskList(task) {
    var sep = arguments.length <= 1 || arguments[1] === undefined ? '' : arguments[1];
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4
    return _regenerator2.default.wrap(function generateTaskList$(_context) {
        while (1) {
            switch (_context.prev = _context.next) {
                case 0:
                    _context.next = 2;
                    return task;

                case 2:
<<<<<<< HEAD
                    if (!(!['exit'].find(function (x) {
                        return x === task._entryPath;
                    }) && task.nextSuccess)) {
=======
                    if (!(task._entryPath !== 'exit' && task.nextSuccess)) {
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4
                        _context.next = 4;
                        break;
                    }

<<<<<<< HEAD
                    return _context.delegateYield(generateTaskList(Task.task(sep, WORKFLOW, TASKS, task.nextSuccess)), 't0', 4);
=======
                    return _context.delegateYield(generateTaskList(ConfigEntry.configEntry(sep, WORKFLOW, TASKS, task.nextSuccess)), 't0', 4);
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4

                case 4:
                case 'end':
                    return _context.stop();
            }
        }
    }, _marked[0], this);
};

<<<<<<< HEAD
// Initiate a task list to push workflow
var tasks = [].concat((0, _toConsumableArray3.default)(generateTaskList(new Task('-', WORKFLOW, TASKS, 'start'), '-')));

console.log("object: ", (0, _keys2.default)(tasks[0].START).length);
=======
// Initiate a starting task to push workflow

var startTask = new Task('-', WORKFLOW, TASKS, 'start');
//
console.log(count++, "!!!startConfig:", startTask);
console.log(count++, 'startConfig.entryId: ' + startTask.entryId);
console.log(count++, " ,startConfig.entryId", startTask.entryId);
console.log(count++, " ,startConfig.nextSuccess", startTask.nextSuccess);

var tasks = [].concat((0, _toConsumableArray3.default)(generateTaskList(new Task('-', WORKFLOW, TASKS, 'start'), '-')));

console.log("VARTATSKS: ", tasks);

var translatedEntry = ConfigEntry.translateConfigEntryReference({}, tasks[1].STEPS.step1);

console.log("translatedEntry", translatedEntry);

console.log("translatedEntry1", translatedEntry.CALL.EXEC.CMD);

//let tasks = Array.from(WorkflowTasks).
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4

//# sourceMappingURL=index.js.map