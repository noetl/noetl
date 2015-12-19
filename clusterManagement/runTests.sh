#!/usr/bin/env bash

# bash showUsage.sh false -> test without rebuilding
build=true
if [ -n "$1" ];then build=$1;fi
if ${build}
then mvn clean compile test
else mvn test
fi
