"use strict";

/**
 * ConfigEntryPath class creates an object that stores result of getConfigEntryPath.
*/

var _slicedToArray2 = require('babel-runtime/helpers/slicedToArray');

var _slicedToArray3 = _interopRequireDefault(_slicedToArray2);

var _classCallCheck2 = require('babel-runtime/helpers/classCallCheck');

var _classCallCheck3 = _interopRequireDefault(_classCallCheck2);

var _createClass2 = require('babel-runtime/helpers/createClass');

var _createClass3 = _interopRequireDefault(_createClass2);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

module.exports = function () {
    function ConfigEntryPath() {
        var _this = this;

        (0, _classCallCheck3.default)(this, ConfigEntryPath);

        var _ConfigEntryPath$getC = ConfigEntryPath.getConfigEntryPath.apply(ConfigEntryPath, arguments);

        var _ConfigEntryPath$getC2 = (0, _slicedToArray3.default)(_ConfigEntryPath$getC, 2);

        var confEntryName = _ConfigEntryPath$getC2[0];
        var confEntryPath = _ConfigEntryPath$getC2[1];

        this._confEntryName = confEntryName;
        this._confEntryPath = confEntryPath;
        this.getConfigEntryName = function () {
            return _this._confEntryName || undefined;
        };
        this.getConfEntryPath = function () {
            return _this._confEntryPath || undefined;
        };
        this._sep = undefined;
    }

    (0, _createClass3.default)(ConfigEntryPath, [{
        key: 'configEntryName',
        set: function set(confName) {
            this._confEntryName = confName;
        },
        get: function get() {
            return this._confEntryName || undefined;
        }
    }, {
        key: 'configEntryPath',
        set: function set(confPath) {
            this._confEntryPath = confPath;
        },
        get: function get() {
            return this._confEntryPath || undefined;
        }
    }], [{
        key: 'configEntryPath',
        value: function configEntryPath() {
            for (var _len = arguments.length, keys = Array(_len), _key = 0; _key < _len; _key++) {
                keys[_key] = arguments[_key];
            }

            return new (Function.prototype.bind.apply(ConfigEntryPath, [null].concat(keys)))();
        }
    }, {
        key: 'getDelimiter',
        value: function getDelimiter() {
            var sep = arguments.length <= 0 || arguments[0] === undefined ? [' ', ':', '.', ',', ';', '|', '-'] : arguments[0];
            return sep;
        }
    }, {
        key: 'getConfigEntryPath',


        /**
         * getConfigEntryPath method gets list of strings ['W','D','A'] and returns 'W:D:A' string.
         * if first item is ':' or ',' or ';', like ['|','W','D','A'] the first item will be used as
         * delimiter - returning 'W|D|A' string.
         * @param [keys]
         * @returns configEntryPath {object}
         */
        value: function getConfigEntryPath() {
            for (var _len2 = arguments.length, keys = Array(_len2), _key2 = 0; _key2 < _len2; _key2++) {
                keys[_key2] = arguments[_key2];
            }

            var checkDelimiter = function checkDelimiter(arg) {
                return arg.length == 1 && ConfigEntryPath.getDelimiter().indexOf(arg) > -1;
            },
                configEntryPath = checkDelimiter(keys[0]) ? [keys.slice(1).join(keys[0]), keys.slice(1).join(':')] : [keys.join(':'), keys.join(':')]; // checkDelimiter returns true if separator exists as a first argument of configEntryPath function that returns array of "Entry Path Name" and "Entry Path"
            return configEntryPath;
        }
    }]);
    return ConfigEntryPath;
}();

//# sourceMappingURL=ConfigEntryPath.js.map