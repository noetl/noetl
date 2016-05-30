"use strict";

var _regenerator = require('babel-runtime/regenerator');

var _regenerator2 = _interopRequireDefault(_regenerator);

var _set = require('babel-runtime/core-js/set');

var _set2 = _interopRequireDefault(_set);

var _getIterator2 = require('babel-runtime/core-js/get-iterator');

var _getIterator3 = _interopRequireDefault(_getIterator2);

var _toConsumableArray2 = require('babel-runtime/helpers/toConsumableArray');

var _toConsumableArray3 = _interopRequireDefault(_toConsumableArray2);

var _map = require('babel-runtime/core-js/map');

var _map2 = _interopRequireDefault(_map);

var _getPrototypeOf = require('babel-runtime/core-js/object/get-prototype-of');

var _getPrototypeOf2 = _interopRequireDefault(_getPrototypeOf);

var _classCallCheck2 = require('babel-runtime/helpers/classCallCheck');

var _classCallCheck3 = _interopRequireDefault(_classCallCheck2);

var _createClass2 = require('babel-runtime/helpers/createClass');

var _createClass3 = _interopRequireDefault(_createClass2);

var _possibleConstructorReturn2 = require('babel-runtime/helpers/possibleConstructorReturn');

var _possibleConstructorReturn3 = _interopRequireDefault(_possibleConstructorReturn2);

var _inherits2 = require('babel-runtime/helpers/inherits');

var _inherits3 = _interopRequireDefault(_inherits2);

var _symbol = require('babel-runtime/core-js/symbol');

var _symbol2 = _interopRequireDefault(_symbol);

var _keys = require('babel-runtime/core-js/object/keys');

var _keys2 = _interopRequireDefault(_keys);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

var ConfigEntry = require('./ConfigEntry'),
    Step = require('./Step'),
    keys = _keys2.default;

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Task class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

var _steps = (0, _symbol2.default)("steps");
var _getStepsRoot = (0, _symbol2.default)("retrieve the starting reference form task START");
var _root = "root"; // root is not a step, but just a forkable entry point for the steps.

/**
 * @class
 * @classdesc Workflow Task's handler.
 * @extends ConfigEntry
 */
module.exports = function (_ConfigEntry) {
    (0, _inherits3.default)(Task, _ConfigEntry);

    function Task() {
        (0, _classCallCheck3.default)(this, Task);

        var _this = (0, _possibleConstructorReturn3.default)(this, (0, _getPrototypeOf2.default)(Task).apply(this, arguments));

        _this[_steps] = new _map2.default();
        _this[_getStepsRoot] = function () {
            return _this.START || undefined;
        };
        if (keys(_this[_getStepsRoot]()).length > 0) {
            _this[_steps].set(_root, new Step(_root, _this[_getStepsRoot]()));
            console.log("this[_steps]", _this[_steps]);
        }
        console.log("entryId", _this.entryPath);
        var entryPathList = _this.entryPath.split(':');
        if (keys(_this.STEPS).length > 0) {
            keys(_this.STEPS).forEach(function (key) {
                console.log("Task key: ", key);_this[_steps].set(key, new (Function.prototype.bind.apply(Step, [null].concat((0, _toConsumableArray3.default)(entryPathList), ["STEPS", key])))());
            });
            keys(_this[_steps]).forEach(function (key) {
                var nextStep = _this[_steps].get(key);
                console.log("this[_steps].get(key).nextSuccess(): ", nextStep);
            });
        }
        if (_this[_steps].size - 1 > 0 && keys(_this.STEPS).length === _this[_steps].size - 1) {}
        console.log("this[_steps]: ", _this[_steps]);
        return _this;
    }

    (0, _createClass3.default)(Task, [{
        key: 'defineDependences',
        value: _regenerator2.default.mark(function defineDependences(step, branch) {
            var done, _iteratorNormalCompletion, _didIteratorError, _iteratorError, _iterator, _step, from, _iteratorNormalCompletion2, _didIteratorError2, _iteratorError2, _iterator2, _step2, to;

            return _regenerator2.default.wrap(function defineDependences$(_context) {
                while (1) {
                    switch (_context.prev = _context.next) {
                        case 0:
                            done = new _map2.default();
                            _iteratorNormalCompletion = true;
                            _didIteratorError = false;
                            _iteratorError = undefined;
                            _context.prev = 4;
                            _iterator = (0, _getIterator3.default)(this[_steps].keys());

                        case 6:
                            if (_iteratorNormalCompletion = (_step = _iterator.next()).done) {
                                _context.next = 40;
                                break;
                            }

                            from = _step.value;

                            done.set(from, new _set2.default());
                            _iteratorNormalCompletion2 = true;
                            _didIteratorError2 = false;
                            _iteratorError2 = undefined;
                            _context.prev = 12;
                            _iterator2 = (0, _getIterator3.default)(this[_steps].get(from).keys());

                        case 14:
                            if (_iteratorNormalCompletion2 = (_step2 = _iterator2.next()).done) {
                                _context.next = 23;
                                break;
                            }

                            to = _step2.value;

                            if (!(this.hasStep(from, to) && !done.get(from).has(to))) {
                                _context.next = 20;
                                break;
                            }

                            done.get(from).add(to);
                            _context.next = 20;
                            return [from, to, this[_steps].get(from).get(to)];

                        case 20:
                            _iteratorNormalCompletion2 = true;
                            _context.next = 14;
                            break;

                        case 23:
                            _context.next = 29;
                            break;

                        case 25:
                            _context.prev = 25;
                            _context.t0 = _context['catch'](12);
                            _didIteratorError2 = true;
                            _iteratorError2 = _context.t0;

                        case 29:
                            _context.prev = 29;
                            _context.prev = 30;

                            if (!_iteratorNormalCompletion2 && _iterator2.return) {
                                _iterator2.return();
                            }

                        case 32:
                            _context.prev = 32;

                            if (!_didIteratorError2) {
                                _context.next = 35;
                                break;
                            }

                            throw _iteratorError2;

                        case 35:
                            return _context.finish(32);

                        case 36:
                            return _context.finish(29);

                        case 37:
                            _iteratorNormalCompletion = true;
                            _context.next = 6;
                            break;

                        case 40:
                            _context.next = 46;
                            break;

                        case 42:
                            _context.prev = 42;
                            _context.t1 = _context['catch'](4);
                            _didIteratorError = true;
                            _iteratorError = _context.t1;

                        case 46:
                            _context.prev = 46;
                            _context.prev = 47;

                            if (!_iteratorNormalCompletion && _iterator.return) {
                                _iterator.return();
                            }

                        case 49:
                            _context.prev = 49;

                            if (!_didIteratorError) {
                                _context.next = 52;
                                break;
                            }

                            throw _iteratorError;

                        case 52:
                            return _context.finish(49);

                        case 53:
                            return _context.finish(46);

                        case 54:
                        case 'end':
                            return _context.stop();
                    }
                }
            }, defineDependences, this, [[4, 42, 46, 54], [12, 25, 29, 37], [30,, 32, 36], [47,, 49, 53]]);
        })
    }, {
        key: 'nextSuccess',
        get: function get() {
            return this.NEXT.SUCCESS || undefined;
        }
    }, {
        key: 'nextFailure',
        get: function get() {
            return this.NEXT.FAILURE || undefined;
        }
    }], [{
        key: 'task',
        value: function task() {
            return new (Function.prototype.bind.apply(Task, [null].concat(Array.prototype.slice.call(arguments))))();
        }
    }]);
    return Task;
}(ConfigEntry);

//export {Task}

//# sourceMappingURL=Task.js.map