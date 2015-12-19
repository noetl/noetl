#!/usr/bin/python
#
# TITLE: Evaluate RESTful calls
# AUTHORS: Alexey Kuksin
# DATE: 15-12-2015
# OBJECTIVE: Manage RESTful process execution
#
#   Copyright 2015 ALEXEY KUXIN
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from __future__ import print_function
import requests

def rest_eval(**kwarg):
    if "get_contexts" in kwarg["FUNC"]:
        return requests.get(kwarg["PATH"])
    if "create_context" in kwarg["FUNC"]:
        return requests.get(kwarg["PATH"],kwarg["PARAMS"])
    if "delete_context" in kwarg["FUNC"]:
        return requests.get(kwarg["PATH"])
    if "deploy_jars" in kwarg["FUNC"]:
        return requests.get(kwarg["PATH"],kwarg["JAR"])
    if "jars" in kwarg["FUNC"]:
        return requests.get(kwarg["PATH"])
    if "jobs" in kwarg["FUNC"]:
        return requests.get(kwarg["PATH"])
    if "submit_job" in kwarg["FUNC"]:
        return requests.post(kwarg["PATH"], params=kwarg["PARAMS"],data=kwarg["DATA"])
    if "check_job_status" in kwarg["FUNC"]:
        return requests.post(kwarg["PATH"]+ "/" +kwarg["JOBID"])
    else:
        return "UNKNOWN REQUEST"


def create_context(path, params):
    return requests.post(path, params)


def delete_context(path):
    return requests.delete(path)


def deploy_jars(path, jar_localfs_path):
    return requests.post(path)


def jars(path):
    return requests.get(path)


def jobs(path):
    return requests.get(path)


def submit_job(path,params, data):
    return requests.post(path, params=params, data=data)


def check_job_status(path, job_id):
    return requests.get(path + "/" + job_id)


def println(test=True, *argv):
    if test:
        print(*argv)


def strip2(*args):
    return ''.join(args[0])[2:-2]