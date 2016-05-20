"use strict";

var _getPrototypeOf = require("babel-runtime/core-js/object/get-prototype-of");

var _getPrototypeOf2 = _interopRequireDefault(_getPrototypeOf);

var _classCallCheck2 = require("babel-runtime/helpers/classCallCheck");

var _classCallCheck3 = _interopRequireDefault(_classCallCheck2);

var _createClass2 = require("babel-runtime/helpers/createClass");

var _createClass3 = _interopRequireDefault(_createClass2);

var _possibleConstructorReturn2 = require("babel-runtime/helpers/possibleConstructorReturn");

var _possibleConstructorReturn3 = _interopRequireDefault(_possibleConstructorReturn2);

var _inherits2 = require("babel-runtime/helpers/inherits");

var _inherits3 = _interopRequireDefault(_inherits2);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

var ConfigEntry = require('./ConfigEntry');

module.exports = function (_ConfigEntry) {
    (0, _inherits3.default)(Task, _ConfigEntry);

    function Task() {
        var _console;

        (0, _classCallCheck3.default)(this, Task);

        (_console = console).log.apply(_console, ["arguments: "].concat(Array.prototype.slice.call(arguments)));
        return (0, _possibleConstructorReturn3.default)(this, (0, _getPrototypeOf2.default)(Task).apply(this, arguments));
    }

    (0, _createClass3.default)(Task, [{
        key: "generateBranches",
        value: function generateBranches() {
            {
                "";
            }
        }
    }, {
        key: "nextSuccess",
        get: function get() {
            return this.NEXT.SUCCESS || undefined;
        }
    }, {
        key: "nextFailure",
        get: function get() {
            return this.NEXT.FAILURE || undefined;
        }
    }, {
        key: "start",
        get: function get() {
            return this.START || undefined;
        }
    }], [{
        key: "task",
        value: function task() {
            return new (Function.prototype.bind.apply(Task, [null].concat(Array.prototype.slice.call(arguments))))();
        }
    }]);
    return Task;
}(ConfigEntry);

//export {Task}

//# sourceMappingURL=Task.js.map