import {Component} from 'angular2/core';
import {EnvVarFormComponent} from './envvar-form.component'
import {RouteConfig, ROUTER_DIRECTIVES} from 'angular2/router';

@Component({
    selector: 'my-app',
    template: `

  <h1>NoETL Config Editor</h1>
  <div class="col-lg-3 col-md-3">
 <div id="wrapper">

        <!-- Sidebar -->
        <div id="sidebar-wrapper">
            <ul class="sidebar-nav">
          <li>
<a [routerLink]="['EnvVarFormComponent']">Environment Variables</a>
</li>
</ul>
</div>
</div>

</div>

 <router-outlet></router-outlet>
`,
    styleUrls: ['app/app.component.css'],
    directives: [ROUTER_DIRECTIVES],
})

@RouteConfig([
    {path:'/envvar-form', name: 'EnvVarFormComponent', component: EnvVarFormComponent}
])
export class AppComponent { }
