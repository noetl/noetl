Project Title - **NoETL**

**1. Introduction**

 A system that helps to automate IT operations, software deployment, provisioning and data management tasks. 
 
 The service provided by tool will be used by DevOps, Software Engineers, Data Scientists, Business Analysts, Database Administrators and Support Engineers.

**The values / benefits:**

NoETL helps to reduce operational costs and time spend on repetitive tasks and deployment scenarios. 

It manages parallel execution of tasks by controlling forks and child processes. 

All major operating systems and cloud infrastructures with distributed environment are supported.

**2. List of Features**

**NoETL Core**
1. Workflow execution handler 
2. Meta-repository handler
3. Operating system command-line interpreter integration (Shell)
4. Remote system call http://wiki.virtualsquare.org/wiki/index.php/Remote_System_Call
5. Remote evaluation https://en.wikipedia.org/wiki/Remote_evaluation
5. RESTful Web services handler 
6. Database integration

**NoETL UI:** 
1. Workflow planner
2. Scheduler
3. Monitoring dashboard
4. Responsive design



**Brief justifications for including these features:**

NoETL relies on reading in steps from a JSON configuration file, each of which has a list of commands that are run sequentially or in parallel and joined together before calling the next step, in the case of a success. 

In the JSON file, each step has code specifying the next action to take.
Each step in the JSON config file has a command list, which is executed by calling the predefined function in NoETL as an action. 

The commands under the steps involves calls to any application via well known protocols - HTTP, JDBC/ODBC, FTP/SFTP, SSH, RPC and so on.

**3. Big Data niche**

Big data processing is divided into two types: batch processing and stream processing. 

Each one has its own advantages and disadvantages.

Chaining these processes together is done using a tool called a "workflow manager".


**The most common solutions today include:**

Oozie (Java, Apache) - http://oozie.apache.org/

Azkaban (Java, LinkedIn) - http://azkaban.github.io/azkaban

Luigi (Python, Spotify) - https://github.com/spotify/luigi

Airflow (Python, AirBnb) - https://github.com/airbnb/airflow

**Brief comparision the features of these applications with NoETL application idea.**

NoETL Executes range based forking vs simple forks.

NoETL relays on Cycle Graph vs DAG.

NoETL supports serverless architecture cloud services vs server based daemons.

NoETL JSON configuration with JS embedded execution handlers vs code based. 

**4. References**

https://en.wikipedia.org/wiki/Workflow_management_system

https://en.wikipedia.org/wiki/Scheduling_(computing)

https://en.wikipedia.org/wiki/Dataflow

https://en.wikipedia.org/wiki/Dataflow_architecture

https://en.wikipedia.org/wiki/Control_flow_diagram

ttp://gojs.net/latest/index.html

http://www.draw2d.org/draw2d/

https://github.com/spotify/luigi

https://media.readthedocs.org/pdf/luigi/latest/luigi.pdf

http://nerds.airbnb.com/airflow/

https://github.com/pinterest/pinball

https://derickbailey.com/2015/08/10/managing-workflow-in-long-running-javascript-processes/







