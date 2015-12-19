#!/usr/bin/env bash
rootPath=/Users/chenguo/Documents/noetl/dt/etl_prod/automation-pipeline

# bash monitorSFTP.sh false -> run without rebuilding
build=true
if [ -n "$1" ];then build=$1;fi
if ${build};then mvn clean -Dmaven.test.skip=true package;fi

java -jar ${rootPath}/target/pipeline-1.0-SNAPSHOT-jar-with-dependencies.jar \
 --conf ${rootPath}/conf.json \
 --sftpToS3
