#!/usr/bin/env bash
rootPath=/Users/chenguo/Documents/noetl/dt/etl_prod/automation-pipeline
stage=s3://noetl-chen
processing=s3://noetl-chen/tmp

logFile=${rootPath}/automation.log
if [ -z "$1" ]
then echo "Using default log file ${logFile}" >> ${logFile}
else logFile=$1
fi

for f in ${rootPath}/ClusterStarted_JFId*
do
	echo "Parsing ${f}..." >> ${logFile}
	jobflow=`echo ${f} | cut -d@ -f2`
	echo "Job flow id: ${jobflow}" >> ${logFile}
	dns=`sed -n '1p' ${f} | cut -d: -f2`
	echo "DNS name: ${dns}" >> ${logFile}
	pipelineFiles=`sed -n '2p' ${f} | cut -d: -f2`
	echo "Files for pipeline: ${pipelineFiles}" >> ${logFile}
	echo "Printing split files:" >> ${logFile}
	IFS=',' read -r -a fileArray <<< "$pipelineFiles"
	for element in "${fileArray[@]}"
    do
        echo "moving $element to tmp directory" >> ${logFile}
        aws s3 mv ${stage}/${element} ${processing}/${element} --profile default
    done
done

#execute NoETL
#remove the ClusterStarted file at the last step of NoETL
