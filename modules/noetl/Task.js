"use strict";

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

var _getStepsRoot = (0, _symbol2.default)("steps start reference"),
    _steps = (0, _symbol2.default)("steps");

var ROOT = "root",
    // root is not a step, but just a forkable entry point for the steps.
STEPS = "STEPS",
    START = "START",
    NEXT = "NEXT";

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
            return _this[START] || undefined;
        };
        try {
            if (keys(_this[_getStepsRoot]()).length > 0) {
                (function () {
                    _this[_steps].set(ROOT, new Step(ROOT, _this[_getStepsRoot]()));
                    var entryPathList = _this.entryPath.split(':');
                    keys(_this[STEPS]).forEach(function (key) {
                        _this[_steps].set(key, new (Function.prototype.bind.apply(Step, [null].concat((0, _toConsumableArray3.default)(entryPathList), [STEPS, key])))());
                    });
                    var _iteratorNormalCompletion = true;
                    var _didIteratorError = false;
                    var _iteratorError = undefined;

                    try {
                        var _loop = function _loop() {
                            var entry = _step.value;

                            var stepName = entry[0],
                                step = entry[1],
                                nextSuccessSteps = step.nextSuccess;
                            keys(nextSuccessSteps).forEach(function (key) {
                                var _this$_steps$get;

                                (_this$_steps$get = _this[_steps].get(stepName)).setChild.apply(_this$_steps$get, (0, _toConsumableArray3.default)(nextSuccessSteps[key]));
                                nextSuccessSteps[key].forEach(function (item, i, arr) {
                                    _this[_steps].get(item).setAncestor(stepName);
                                    _this[_steps].get(item).setBranch(['0', ''].find(function (x) {
                                        return x === key;
                                    }) ? item : key);
                                });
                            });
                        };

                        for (var _iterator = (0, _getIterator3.default)(_this[_steps]), _step; !(_iteratorNormalCompletion = (_step = _iterator.next()).done); _iteratorNormalCompletion = true) {
                            _loop();
                        }
                    } catch (err) {
                        _didIteratorError = true;
                        _iteratorError = err;
                    } finally {
                        try {
                            if (!_iteratorNormalCompletion && _iterator.return) {
                                _iterator.return();
                            }
                        } finally {
                            if (_didIteratorError) {
                                throw _iteratorError;
                            }
                        }
                    }
                })();
            } else {
                throw new Error("Steps starting entry point doesn't exists");
            }
        } catch (e) {
            console.error("Task initializing error ", e.message);
        } finally {
            console.log("this[_steps]: ", _this[_steps]);
        }
        return _this;
    }

    (0, _createClass3.default)(Task, [{
        key: 'nextSuccess',
        get: function get() {
            return this[NEXT].SUCCESS || undefined;
        }
    }, {
        key: 'nextFailure',
        get: function get() {
            return this[NEXT].FAILURE || undefined;
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