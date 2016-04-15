/**
 * Created by abalachander on 2/18/16.
 */
import {Component} from 'angular2/core';
import {NgForm}    from 'angular2/common';
import { EnvVar }    from './envvar';
@Component({
    selector: 'envvar-form',
    templateUrl: 'app/envvar-form.component.html'
})
export class EnvVarFormComponent {
roots = ['./','/home/hadoop'];
model = new EnvVar(1, 'localhost', this.roots[0], '/tmp');
    submitted = false;
    onSubmit() { this.submitted = true; }
    // TODO: Remove this when we're done
    get diagnostic() { return JSON.stringify(this.model); }

    active = true;
    newEnvVar()
    {
        this.model = new EnvVar(42, '', '');
        this.active = false;
        setTimeout(()=> this.active=true, 0);

    }
}
