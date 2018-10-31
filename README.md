# [NoETL](https://github.com/noetl/noetl/wiki)
NoETL's (Not Only ETL) current python version is a prototype of a system to manage the sequence of the process execution by controlling forks and child processes. 

[Functionality of the prototype is described on wiki](https://github.com/noetl/noetl/wiki)

[Gitter chat](https://gitter.im/noetl/noetl)

## Quick Start
 `brew install etcd`

 `brew services start etcd`

 `brew install dep`
 
 `dep ensure`
 
 `go run main.go`
 
 `curl -XPOST -d'{"id":"/templates/demo2", "config": "the contents of the config /templates/demo2"}' localhost:8888/flow/v1/template`
 
 `curl -XGET -d'{"id":"/templates/demo2"}' localhost:8888/flow/v1/template`
 
 `curl -XPUT -d'{"id":"/templates/demo2", "config": "the contents of the config demo1"}' localhost:8888/flow/v1/template`
 
 `curl -XDELETE -d'{"id":"/templates/"}' localhost:8888/flow/v1/template`
 
 `curl -XDELETE -d'{"path":"/templates/dirname/"}' localhost:8888/flow/v1/templates`
 
 `curl -XGET localhost:8888/flow/v1/dirtree`
 
 `curl -XPOST -d'{"name": "templates","root": true,"isOpen": true,"children": []}' localhost:8888/flow/v1/dirtree`
