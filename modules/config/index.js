var nconf = require('nconf');

nconf.argv()
    .env()
    .file({
        file: process.cwd() + '/modules/config/config.json'
    });

switch(process.env.NODEENV) {
    case 'DEV':
        console.log('Loading DEV Configuration Settings');
        nconf.file('custom', { file: './modules/config/dev-config.json' });
        break;

    case 'QA':
        console.log('Loading QA Configuration Settings');
        nconf.file('custom', { file: './modules/config/qa-config.json' });
        break;

    case 'PROD':
        console.log('Loading PROD Configuration Settings');
        nconf.file('custom', { file: './modules/config/prod-config.json' });
        break;

    case 'DENALI':
        console.log('Loading DENALI Configuration Settings');
        nconf.file('custom', { file: './modules/config/denali-config.json' });
        break;

    default:
        console.log('Loading DEV Configuration Settings');
        nconf.file('custom', { file: './modules/config/dev-config.json' });
        break;
}

module.exports = nconf;
