System.register([], function(exports_1) {
    var EnvVar;
    return {
        setters:[],
        execute: function() {
            /**
             * Created by abalachander on 2/18/16.
             */
            EnvVar = (function () {
                function EnvVar(id, host, root, tmp) {
                    this.id = id;
                    this.host = host;
                    this.root = root;
                    this.tmp = tmp;
                }
                return EnvVar;
            })();
            exports_1("EnvVar", EnvVar);
        }
    }
});
//# sourceMappingURL=envvar.js.map