System.register(['angular2/core', './envvar'], function(exports_1) {
    var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
        var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
        if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
        else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
        return c > 3 && r && Object.defineProperty(target, key, r), r;
    };
    var __metadata = (this && this.__metadata) || function (k, v) {
        if (typeof Reflect === "object" && typeof Reflect.metadata === "function") return Reflect.metadata(k, v);
    };
    var core_1, envvar_1;
    var EnvVarFormComponent;
    return {
        setters:[
            function (core_1_1) {
                core_1 = core_1_1;
            },
            function (envvar_1_1) {
                envvar_1 = envvar_1_1;
            }],
        execute: function() {
            EnvVarFormComponent = (function () {
                function EnvVarFormComponent() {
                    this.roots = ['./', '/home/hadoop'];
                    this.model = new envvar_1.EnvVar(1, 'localhost', this.roots[0], '/tmp');
                    this.submitted = false;
                    this.active = true;
                }
                EnvVarFormComponent.prototype.onSubmit = function () { this.submitted = true; };
                Object.defineProperty(EnvVarFormComponent.prototype, "diagnostic", {
                    // TODO: Remove this when we're done
                    get: function () { return JSON.stringify(this.model); },
                    enumerable: true,
                    configurable: true
                });
                EnvVarFormComponent.prototype.newEnvVar = function () {
                    var _this = this;
                    this.model = new envvar_1.EnvVar(42, '', '');
                    this.active = false;
                    setTimeout(function () { return _this.active = true; }, 0);
                };
                EnvVarFormComponent = __decorate([
                    core_1.Component({
                        selector: 'envvar-form',
                        templateUrl: 'app/envvar-form.component.html'
                    }), 
                    __metadata('design:paramtypes', [])
                ], EnvVarFormComponent);
                return EnvVarFormComponent;
            })();
            exports_1("EnvVarFormComponent", EnvVarFormComponent);
        }
    }
});
//# sourceMappingURL=envvar-form.component.js.map