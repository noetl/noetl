# NoETL
NoETL's (Not Only ETL) current Nodejs version is a prototype of a system to manage the sequence of the process execution by controlling forks and child processes.

Functionality of the prototype is described on wiki - https://github.com/noetl/noetl/wiki


## ToDo

1. Create "RunShell" class that executes shell scripts remotely.

as of example shown in noetl/conf/coursor.inherit.cfg.v2.json -> step2
we have to read a list of URLs and open ssh connection to each of the host.
if number of "THREAD" is greater then "0" we need to create a list of command list that should be call in parallel.
e.g:
"CALL": {
	"ACTION": "runShell",
	"THREAD": "4",
	"CURSOR": {
	"RANGE": [
	{"FROM":"1","TO":"11","INCREMENT": "1"}],
		"DATATYPE": "integer"
	},
	"EXEC": {
	"URL": ["10.10.10.1","10.10.10.2","10.10.10.3","10.10.10.4","10.10.10.5"],
	"CMD": [
			["echo \"HelloWorld []\" > /tmp/HelloWorld[].test"],
				["cat /tmp/HelloWorld[].test"]
			]
		}
	}

in this particular case we should keep five open sessions to all 5 remote hosts:

ssh 10.10.10.1
ssh 10.10.10.2
ssh 10.10.10.3
ssh 10.10.10.4
ssh 10.10.10.5

and for each node we have to run 4 parallel process at the same a time:
ssh ssh 10.10.10.1
[
echo \"HelloWorld 1\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld1.test
echo \"HelloWorld 2\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld2.test
echo \"HelloWorld 3\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld3.test
echo \"HelloWorld 4\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld4.test
]

ssh ssh 10.10.10.2
[
echo \"HelloWorld 1\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld1.test
echo \"HelloWorld 2\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld2.test
echo \"HelloWorld 3\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld3.test
echo \"HelloWorld 4\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld4.test
]
...
ssh ssh 10.10.10.5
[
echo \"HelloWorld 1\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld1.test
echo \"HelloWorld 2\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld2.test
echo \"HelloWorld 3\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld3.test
echo \"HelloWorld 4\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld4.test
]

if any of process on any host is failed and we have MAX_FAILURES parameter specified as a step's property:
"MAX_FAILURES": "1",
"WAITTIME": "10s"

we need to run the failed command again after 10 second and wait till all currently running processes are finished.
If any of process that has been run twice is failed again, we should stop the Step execution and report the failure.
If all 4 commands successfully finished then next 4 cursor's items to be apply for each remote host's session.
e.g
ssh ssh 10.10.10.1
[
echo \"HelloWorld 5\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld5.test
echo \"HelloWorld 6\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld6.test
echo \"HelloWorld 7\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld7.test
echo \"HelloWorld 8\" > /tmp/HelloWorld1.test && cat /tmp/HelloWorld8.test
]
...
 and so on on each node.

ElseIf "THREAD":"0" is zero or empty we have to run all cursor's items at once on each node.

Library to be used:
https://www.npmjs.com/browse/keyword/ssh2
https://github.com/mscdex/ssh2

Implementation references:
https://www.npmjs.com/package/ssh2-exec
https://github.com/wdavidw/node-ssh2-exec

https://www.npmjs.com/package/co-ssh
https://github.com/tj/co-ssh/blob/master/index.js

Both reference link doesn't have ES6 class implemented. We have to try to make it in line with ConfigEntry.es6 implementation.

2. We have to implement the same mechanism to esteblish a RESTful call in the same manner.

