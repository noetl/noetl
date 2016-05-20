"use strict";

/**
 * ConfigEntryPath class creates an object that stores result of getConfigEntryPath.
*/

module.exports =
    class ConfigEntryPath{
    constructor(...keys){
        let [confEntryName,confEntryPath] = ConfigEntryPath.getConfigEntryPath(...keys)
        this._confEntryName = confEntryName
        this._confEntryPath = confEntryPath
        this.getConfigEntryName = () => { return this._confEntryName || undefined}
        this.getConfEntryPath = () => { return this._confEntryPath || undefined}
        this._sep = undefined
    }
    static configEntryPath(...keys) {
        return new ConfigEntryPath(...keys)
    }
    static getDelimiter(sep = [' ',':','.',',',';','|','-']) {return sep;};

    /**
     * getConfigEntryPath method gets list of strings ['W','D','A'] and returns 'W:D:A' string.
     * if first item is ':' or ',' or ';', like ['|','W','D','A'] the first item will be used as
     * delimiter - returning 'W|D|A' string.
     * @param [keys]
     * @returns configEntryPath {object}
     */
    static getConfigEntryPath(...keys) {
        let checkDelimiter = arg => arg.length==1 && ConfigEntryPath.getDelimiter().indexOf(arg)>-1, configEntryPath = checkDelimiter(keys[0])  ? [keys.slice(1).join(keys[0]),keys.slice(1).join(':')] : [keys.join(':'),keys.join(':') ]  // checkDelimiter returns true if separator exists as a first argument of configEntryPath function that returns array of "Entry Path Name" and "Entry Path"
        return configEntryPath
    }
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
};

