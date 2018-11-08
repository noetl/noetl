# [NoETL](https://github.com/noetl/noetl/wiki)
NoETL's (Not Only ETL) current python version is a prototype of a system to manage the sequence of the process execution by controlling forks and child processes. 

[Functionality of the prototype is described on wiki](https://github.com/noetl/noetl/wiki)

[Gitter chat](https://gitter.im/noetl/noetl)

## Quick Start
To bring up etcd and noetl instance for development run:
 ```
 docker-compose up
 ```
 It will build and run docker containers for each instance. Every time you make any changes and save any file in noetl project, noetl server will be restarted automatically.
 
 ## Examples
 ```
curl -XPOST -d'{"id":"/templates/demo2", "config": "the contents of the config /templates/demo2"}' localhost:8888/flow/template 

curl -XGET -d'{"id":"/templates/demo2"}' localhost:8888/flow/template

curl -XPUT --data @conf/sample-demo-2.json localhost:8888/flow/template

curl -XDELETE -d'{"id":"/templates/"}' localhost:8888/flow/template

curl -XDELETE -d'{"path":"/templates/dirname/"}' localhost:8888/flow/templates 

curl -XGET localhost:8888/flow/dirtree

curl -XPOST -d'{"name": "templates","root": true,"isOpen": true,"children": []}' localhost:8888/flow/dirtree

curl -XPOST -d'{"id": "/templates/demo-2","workflow": {}}' localhost:8888/flow/run
```
