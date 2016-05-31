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

var _ancestor = (0, _symbol2.default)("incoming steps"),
    _child = (0, _symbol2.default)("next steps"),
    _branch = (0, _symbol2.default)("branch name"),
    _status = "step status"; // [READY||RUNNING||WAITING||FINISHED||FAILED]

/**
 * @class Step
 * @classdesc Workflow Step's handler.
 * @extends ConfigEntry
 */
module.exports = function (_ConfigEntry) {
    (0, _inherits3.default)(Step, _ConfigEntry);

    function Step() {
        (0, _classCallCheck3.default)(this, Step);

        var _this = (0, _possibleConstructorReturn3.default)(this, (0, _getPrototypeOf2.default)(Step).apply(this, arguments));

        _this[_ancestor] = new _set2.default();
        _this[_child] = new _set2.default();
        _this[_branch] = "0";
        _this[_status] = undefined;
        if (arguments[0] === "root") {
            _this.NEXT = { "SUCCESS": (0, _assign2.default)({}, arguments[1]) };
        }

        return _this;
    }

    (0, _createClass3.default)(Step, [{
        key: "setAncestor",
        value: function setAncestor() {
            var _this2 = this;

            for (var _len = arguments.length, ancestor = Array(_len), _key = 0; _key < _len; _key++) {
                ancestor[_key] = arguments[_key];
            }

            ancestor.forEach(function (item) {
                return _this2[_ancestor].add(item);
            });
        }
    }, {
        key: "setChild",
        value: function setChild() {
            var _this3 = this;

            for (var _len2 = arguments.length, child = Array(_len2), _key2 = 0; _key2 < _len2; _key2++) {
                child[_key2] = arguments[_key2];
            }

            child.forEach(function (item) {
                return _this3[_child].add(item);
            });
        }
    }, {
        key: "setBranch",
        value: function setBranch(branch) {
            this[_branch] = branch;
        }
    }, {
        key: "getAncestor",
        value: function getAncestor() {
            return this[_ancestor] || undefined;
        }
    }, {
        key: "getChild",
        value: function getChild() {
            return this[_child] || undefined;
        }
    }, {
        key: "getBranch",
        value: function getBranch() {
            return this[_branch] || undefined;
        }
    }, {
        key: "getCall",
        value: function getCall() {
            return this.CALL || undefined;
        }
    }, {
        key: "getCursor",
        value: function getCursor() {
            return this.CURSOR || undefined;
        }
    }, {
        key: "getAction",
        value: function getAction() {
            return this.ACTION || undefined;
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