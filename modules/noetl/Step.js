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

var Task = require('./Task');

module.exports = function (_Task) {
    (0, _inherits3.default)(Step, _Task);

    function Step() {
        (0, _classCallCheck3.default)(this, Step);
        return (0, _possibleConstructorReturn3.default)(this, (0, _getPrototypeOf2.default)(Step).apply(this, arguments));
    }

    (0, _createClass3.default)(Step, [{
        key: "call",
        get: function get() {
            return this.CALL || undefined;
        }
    }, {
        key: "action",
        get: function get() {
            return this.ACTION || undefined;
        }
    }, {
        key: "cursor",
        get: function get() {
            return this.CURSOR || undefined;
        }
    }], [{
        key: "step",
        value: function step() {
            return new (Function.prototype.bind.apply(Step, [null].concat(Array.prototype.slice.call(arguments))))();
        }
    }]);
    return Step;
}(Task);

//export  {Step}

//# sourceMappingURL=Step.js.map