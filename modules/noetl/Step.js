"use strict";

var _assign = require("babel-runtime/core-js/object/assign");

var _assign2 = _interopRequireDefault(_assign);

var _set = require("babel-runtime/core-js/set");

var _set2 = _interopRequireDefault(_set);

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

var _symbol = require("babel-runtime/core-js/symbol");

var _symbol2 = _interopRequireDefault(_symbol);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

var ConfigEntry = require('./ConfigEntry');

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io //////////////// NoETL Step class //////////////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

var _ancestor = (0, _symbol2.default)("list of incoming steps");
var _child = (0, _symbol2.default)("list of next steps");
var _branch = (0, _symbol2.default)("branch name");
var _status = "status of step"; // [READY||RUNNING||WAITING||FINISHED||FAILED]

/**
 * @class Step
 * @classdesc Workflow Step's handler.
 * @extends Task
 */
module.exports = function (_ConfigEntry) {
    (0, _inherits3.default)(Step, _ConfigEntry);

    function Step() {
        (0, _classCallCheck3.default)(this, Step);

        var _this = (0, _possibleConstructorReturn3.default)(this, (0, _getPrototypeOf2.default)(Step).apply(this, arguments));

        _this[_ancestor] = new _set2.default();
        _this[_child] = new _set2.default();
        _this[_branch] = undefined;
        _this[_status] = "READY";
        if (arguments[0] === "root") {
            _this.NEXT = { "SUCCESS": (0, _assign2.default)({}, arguments[1]) };
        }

        return _this;
    }

    (0, _createClass3.default)(Step, [{
        key: "ancestor",
        set: function set() {
            var _ancestor2;

            (_ancestor2 = this[_ancestor]).add.apply(_ancestor2, arguments);
        },
        get: function get() {
            return this[_ancestor] || undefined;
        }
    }, {
        key: "child",
        set: function set() {
            var _child2;

            (_child2 = this[_child]).add.apply(_child2, arguments);
        },
        get: function get() {
            return this[_child] || undefined;
        }
    }, {
        key: "branch",
        set: function set(branch) {
            this[_branch] = branch || undefined;
        },
        get: function get() {
            return this[_branch] || undefined;
        }
    }, {
        key: "nextSuccess",
        get: function get() {
            return this["NEXT"] || undefined;
        }
    }, {
        key: "nextFailure",
        get: function get() {
            return this.NEXT.FAILURE || undefined;
        }
    }, {
        key: "getCall",
        get: function get() {
            return this.CALL || undefined;
        }
    }, {
        key: "getCursor",
        get: function get() {
            return this.CURSOR || undefined;
        }
    }, {
        key: "getAction",
        get: function get() {
            return this.ACTION || undefined;
        }
    }], [{
        key: "step",
        value: function step() {
            return new (Function.prototype.bind.apply(Step, [null].concat(Array.prototype.slice.call(arguments))))();
        }
    }]);
    return Step;
}(ConfigEntry);

//export  {Step}

//# sourceMappingURL=Step.js.map