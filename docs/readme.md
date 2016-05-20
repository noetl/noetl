# ToDo
one way binding/ two way bindings - angular
login screen - userid/ password
return status from mongodb if success/failed
div - failed - red/ success green
koa - angular
transpile es6 by babel
change language compatablity to es6
add file wathcer for es6 files.
change file extention. remove -compile in the file name.

# Required modules

```npm install ./api/user/ --save```

To handle Json configurations:
https://www.npmjs.com/package/nconf

General modules:
```npm install koa koa-mount --save```
```npm install co --save-dev```
```npm install koa-basic-auth --save```
```npm install koa koa-route co-body co-monk monk --save```
```npm install mocha co should supertest --save-dev```


## For testing:
https://github.com/visionmedia/supertest (npm install mocha supertest --save-dev)
https://www.npmjs.com/package/should
https://mochajs.org/  (npm install mocha --save-dev)
 
# Troubleshooting

```npm config -g set python \"/usr/bin/python2\"```
```npm cache clean```
```sudo npm install bson```
```sudo npm update```
```npm install -g node-gyp```
```npm install mongoose```


** Problem:
var skinClassName = 'Skin' + NativeClass.name;
https://github.com/Automattic/monk/issues/91
** Solution:
```npm uninstall mongodb --save```
```npm install mongodb@1.4 --save```

** Problem:
[Error: Cannot find module '../build/Release/bson'] code: 'MODULE_NOT_FOUND' } js-bson: Failed to load c++ bson extension, using pure JS version
http://stackoverflow.com/questions/28651028/cannot-find-module-build-release-bson-code-module-not-found-js-bson
** Solution:
```npm config -g set python "/usr/bin/python2"```
```npm cache clean```
```npm install bson```
```npm update```
```npm install -g node-gyp```
```npm install mongoose```
```node-gyp rebuild```

or
```vi ~/projects/noetl/noetl/api/user/node_modules/mongodb/node_modules/bson/ext/index.js```
change the line ```bson = require('../build/Release/bson');``` to ```bson = require('bson');```

# Notes
