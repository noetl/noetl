#!/usr/bin/env bash

# bash showUsage.sh false -> run without rebuilding
build=true
if [ -n "$1" ];then build=$1;fi
if ${build};then mvn clean -Dmaven.test.skip=true package;fi

java -jar target/pipeline-1.0-SNAPSHOT-jar-with-dependencies.jar -h
