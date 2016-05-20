"use strict";
var nconf = require('nconf');

/**
 * ConfigEntry class creates an object for given config path.
 * @param configEntryPath {Object}
 */

module.exports = class ConfigEntry{
    constructor() {
        let [confEntryName,confEntryPath] = ConfigEntry.getConfigEntryPath(...arguments)
        this._confEntryName = confEntryName
        this._confEntryPath = confEntryPath
        this.getConfigEntryName = () => { return this._confEntryName || undefined}
        this.getConfEntryPath = () => { return this._confEntryPath || undefined}
        //configEntryPath = (arguments.length>1) ? ConfigEntryPath.configEntryPath(...arguments) : configEntryPath;
        let validatedConfigEntry = ConfigEntry.validateConfigEntry(this.getConfEntryPath());
        if (validatedConfigEntry) {
            this._entryId = this.configEntryName;
            this._entryPath = this.configEntryPath;
            Object.assign(this, ConfigEntry.translateConfigEntryReference({},validatedConfigEntry));
        }
    }
    static configEntry() {
        return new ConfigEntry(...arguments)
    }
    /**
     * isObject checks if input is an object and not is an array and not is null.
     * @param item
     * @returns {boolean}
     */
    static isObject(item) {
        return (item && typeof item === 'object' && !Array.isArray(item) && item !== null);
    }

    /**
     * getConfigEntryPath method gets list of strings ['W','D','A'] and returns 'W:D:A' string.
     * if first item is ':' or ',' or ';', like ['|','W','D','A'] the first item will be used as
     * delimiter - returning 'W|D|A' string.
     * @param [keys]
     * @returns configEntryPath {object}
     */
    static getConfigEntryPath(...keys) {
        let checkDelimiter = arg => arg.length==1 && ConfigEntry.getDelimiter().indexOf(arg)>-1, configEntryPath = checkDelimiter(keys[0])  ? [keys.slice(1).join(keys[0]),keys.slice(1).join(':')] : [keys.join(':'),keys.join(':') ]  // checkDelimiter returns true if separator exists as a first argument of configEntryPath function that returns array of "Entry Path Name" and "Entry Path"
        return configEntryPath
    }
    static getDelimiter(sep = [' ',':','.',',',';','|','-']) {return sep;};
    set configEntryName(confName) {
        this._confEntryName = confName
    }
    set configEntryPath(confPath) {
        this._confEntryPath = confPath
    }
    get configEntryName() {
        return this._confEntryName || undefined;
    }
    get configEntryPath() {
        return this._confEntryPath || undefined;
    }

    /**
     * validatedConfigValue function gets delimited path string 'Node1:Node2:Node3' and returns 'Node3' value.
     * @param entryPath String
     * @returns validatedConfigValue {object}
     */
    static validateConfigEntry(entryPath){
        let validatedConfigValue = nconf.get(entryPath) || undefined;
        return validatedConfigValue;
    };

    /**
     * translateConfigEntryReference makes a deep copy of an object replacing values for the referenced values.
     * @param refValue
     * @param srcValue
     * @returns {object} || [array] || string
     */
    static translateConfigEntryReference(refValue, srcValue) {
        const REGEX = /\${(.*?)}/g;
        if (ConfigEntry.isObject(refValue) && ConfigEntry.isObject(srcValue))  {
            Object.keys(srcValue).forEach(key => {
                if (ConfigEntry.isObject(srcValue[key])) {
                    if (!refValue[key]) Object.assign(refValue, { [key]: {} });
                    ConfigEntry.translateConfigEntryReference(refValue[key], srcValue[key]);
                } else {
                    Object.assign(refValue, { [key]: ConfigEntry.translateConfigEntryReference(null,srcValue[key]) });
                }
            });
        } else if (Array.isArray(srcValue)) {
                return  srcValue.map(item => { return ConfigEntry.translateConfigEntryReference(null,item);})
        } else if (REGEX.test(srcValue)) {
                let val = srcValue.replace(REGEX, (match,p1) => {return nconf.get(p1.replace(/\./g, ":"));});
                return ConfigEntry.translateConfigEntryReference( ConfigEntry.isObject(val) ? {} : null, val);
        } else {
            return srcValue;
        }

        return refValue;
    }

    get entryId (){
        return this._entryId || undefined;
    }

};
//export {ConfigEntry}