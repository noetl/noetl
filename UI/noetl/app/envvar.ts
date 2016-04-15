/**
 * Created by abalachander on 2/18/16.
 */
export class EnvVar {
    
    constructor(
        public id: number,
        public host: string,
        public root: string,
        public tmp?: string
    ) {
    }

   /* addNewEnvVar() {
        var newEnvVar = {
            envName: dlg.envName,
            envValue: dlg.Value,
            envtype: dlg.TYpe

        };
        this.EnvVars.push(newEnvVar);

    }
  /*this.meta = [];
    this.meta.push({
        propertyName: 'host',
        displayName: 'HostAddress',
        type:
    })*/
}


