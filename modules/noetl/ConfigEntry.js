"use strict";

var _defineProperty2 = require("babel-runtime/helpers/defineProperty");

var _defineProperty3 = _interopRequireDefault(_defineProperty2);

var _keys = require("babel-runtime/core-js/object/keys");

var _keys2 = _interopRequireDefault(_keys);

var _typeof2 = require("babel-runtime/helpers/typeof");

var _typeof3 = _interopRequireDefault(_typeof2);

var _assign = require("babel-runtime/core-js/object/assign");

var _assign2 = _interopRequireDefault(_assign);

var _slicedToArray2 = require("babel-runtime/helpers/slicedToArray");

var _slicedToArray3 = _interopRequireDefault(_slicedToArray2);

var _classCallCheck2 = require("babel-runtime/helpers/classCallCheck");

var _classCallCheck3 = _interopRequireDefault(_classCallCheck2);

var _createClass2 = require("babel-runtime/helpers/createClass");

var _createClass3 = _interopRequireDefault(_createClass2);

var _symbol = require("babel-runtime/core-js/symbol");

var _symbol2 = _interopRequireDefault(_symbol);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

var nconf = require('nconf');

// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////
// www.noetl.io ///////////////// NoETL ConfigEntry class //////////////////////////////////////////////////////////////
// www.noetl.io ////////////////////////////////////////////////////////////////////////////////////////////////////////

var _confEntryName = (0, _symbol2.default)("config entry name");
var _confEntryPath = (0, _symbol2.default)("config entry path");
var _entryId = (0, _symbol2.default)("object entry id");
var _entryPath = (0, _symbol2.default)("object entry path");
var _getConfigEntryName = (0, _symbol2.default)("retrieve entry name");
var _getConfEntryPath = (0, _symbol2.default)("retrieve entry path");

/**
 * @class ConfigEntry
 * @classdesc The main class to be used to access configuration entries.
 *
 * @description class creates an object for given config path
 * @param ...arguments
 * @example
 * var workflow = new ConfigEntry(
 * '-',                                     // delimiter to be used as for this._confEntryName
 * 'WORKFLOW',
 * 'TIMESTAMP'
 * );
 */
module.exports = function () {
    function ConfigEntry() {
        var _this = this;

        (0, _classCallCheck3.default)(this, ConfigEntry);

        var _ConfigEntry$getConfi = ConfigEntry.getConfigEntryPath.apply(ConfigEntry, arguments);

        var _ConfigEntry$getConfi2 = (0, _slicedToArray3.default)(_ConfigEntry$getConfi, 2);

        var confEntryName = _ConfigEntry$getConfi2[0];
        var confEntryPath = _ConfigEntry$getConfi2[1];

        this[_confEntryName] = confEntryName;
        this[_confEntryPath] = confEntryPath;
        this[_getConfigEntryName] = function () {
            return _this[_confEntryName] || undefined;
        };
        this[_getConfEntryPath] = function () {
            return _this[_confEntryPath] || undefined;
        };
        //configEntryPath = (arguments.length>1) ? ConfigEntryPath.configEntryPath(...arguments) : configEntryPath;
        var validatedConfigEntry = ConfigEntry.validateConfigEntry(this[_getConfEntryPath]());
        if (validatedConfigEntry) {
<<<<<<< HEAD
            this[_entryId] = this.configEntryName;
            this[_entryPath] = this.configEntryPath;
=======
            this._entryId = this.configEntryName;
            this._entryPath = this.configEntryPath;
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4
            (0, _assign2.default)(this, ConfigEntry.translateConfigEntryReference({}, validatedConfigEntry));
        }
    }

    (0, _createClass3.default)(ConfigEntry, [{
        key: "configEntryName",
        set: function set(confName) {
            this[_confEntryName] = confName;
        },
        get: function get() {
            return this[_confEntryName] || undefined;
        }
    }, {
        key: "configEntryPath",
        set: function set(confPath) {
            this[_confEntryPath] = confPath;
        },
        get: function get() {
            return this[_confEntryPath] || undefined;
        }
    }, {
        key: "entryId",
        get: function get() {
            return this[_entryId] || undefined;
        }
    }, {
        key: "entryPath",
        get: function get() {
            return this[_entryPath] || undefined;
        }

        /**
         * validatedConfigValue function gets delimited path string 'Node1:Node2:Node3' and returns 'Node3' value.
         * @param entryPath String
         * @returns validatedConfigValue {object}
         */

    }], [{
        key: "configEntry",
        value: function configEntry() {
            return new (Function.prototype.bind.apply(ConfigEntry, [null].concat(Array.prototype.slice.call(arguments))))();
        }

        /**
         * isObject checks if input is an object and not is an array and not is null.
         * @param item {object}
         * @returns {boolean}
         */

    }, {
        key: "isObject",
        value: function isObject(item) {
            return item && (typeof item === "undefined" ? "undefined" : (0, _typeof3.default)(item)) === 'object' && !Array.isArray(item) && item !== null;
        }

        /**
         * getConfigEntryPath method gets list of strings ['W','D','A'] and returns 'W:D:A' string.
         * if first item is ':' or ',' or ';', like ['|','W','D','A'] the first item will be used as
         * delimiter - returning 'W|D|A' string.
         * @param [keys]
         * @returns configEntryPath {object}
         */

    }, {
        key: "getConfigEntryPath",
        value: function getConfigEntryPath() {
            for (var _len = arguments.length, keys = Array(_len), _key = 0; _key < _len; _key++) {
                keys[_key] = arguments[_key];
            }

            var checkDelimiter = function checkDelimiter(arg) {
                return arg.length == 1 && ConfigEntry.getDelimiter().indexOf(arg) > -1;
            },
                configEntryPath = checkDelimiter(keys[0]) ? [keys.slice(1).join(keys[0]), keys.slice(1).join(':')] : [keys.join(':'), keys.join(':')]; // checkDelimiter returns true if separator exists as a first argument of configEntryPath function that returns array of "Entry Path Name" and "Entry Path"
            return configEntryPath;
        }
    }, {
        key: "getDelimiter",
        value: function getDelimiter() {
            var sep = arguments.length <= 0 || arguments[0] === undefined ? [' ', ':', '.', ',', ';', '|', '-'] : arguments[0];
            return sep;
        }
    }, {
        key: "validateConfigEntry",
        value: function validateConfigEntry(entryPath) {
            var validatedConfigValue = nconf.get(entryPath) || undefined;
            return validatedConfigValue;
        }
    }, {
<<<<<<< HEAD
        key: "translateConfigEntryReference",
=======
        key: 'translateConfigEntryReference',
>>>>>>> 993f4501ea1cde00513c0ee0423a27c0e7aad1d4


        /**
         * translateConfigEntryReference makes a deep copy of an object replacing values for the referenced values.
         * @param refValue
         * @param srcValue
         * @returns {object} || [array] || string
         */
        value: function translateConfigEntryReference(refValue, srcValue) {
            var REGEX = /\${(.*?)}/g;
            if (ConfigEntry.isObject(refValue) && ConfigEntry.isObject(srcValue)) {
                (0, _keys2.default)(srcValue).forEach(function (key) {
                    if (ConfigEntry.isObject(srcValue[key])) {
                        if (!refValue[key]) (0, _assign2.default)(refValue, (0, _defineProperty3.default)({}, key, {}));
                        ConfigEntry.translateConfigEntryReference(refValue[key], srcValue[key]);
                    } else {
                        (0, _assign2.default)(refValue, (0, _defineProperty3.default)({}, key, ConfigEntry.translateConfigEntryReference(null, srcValue[key])));
                    }
                });
            } else if (Array.isArray(srcValue)) {
                return srcValue.map(function (item) {
                    return ConfigEntry.translateConfigEntryReference(null, item);
                });
            } else if (REGEX.test(srcValue)) {
                var val = srcValue.replace(REGEX, function (match, p1) {
                    return nconf.get(p1.replace(/\./g, ":"));
                });
                return ConfigEntry.translateConfigEntryReference(ConfigEntry.isObject(val) ? {} : null, val);
            } else {
                return srcValue;
            }
            return refValue;
        }
    }]);
    return ConfigEntry;
}();
//export {ConfigEntry}

//# sourceMappingURL=ConfigEntry.js.map