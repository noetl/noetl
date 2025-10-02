# Core Concept

1. Playbook is a manifest file of the workflow.
2. Server api provides interface for UI, CLI and Workers
3. Worker pools arranges resources to execute actual tasks of the playbooks.

Playbook has 4 section:
- metadata: contains name  and path and version and description of the playbook
- workflow: has a steps and transition logic
- workbook: is a namespace to keep named action types of the playbook that can be refered from the steps.
- workload: is a section for the static variables that can be override or merged with payload passed to the playbook.

Step:
1. Steps defined in the workflow section of the playbook.  

2. Step has a type, e.g:  type: workbook or type: python or type: playbook.   
2.1. If type: playbook and step has attribute path: examples/weather_loop then step will schedule this playbook for execution and pass context to it.  
2.2. If type: workbook and step has attribute name: task_name then noetl will lookup the action type by name in the workbook section and schedule it for execution.  
2.3  If type: python ot http or duckdb or postgres or secret - noetl will schedule the step action type with it's attributes to execute on workers' pool.  

3. Iteration is modeled with an iterator step (`type: iterator`). It executes a nested task once per element of `collection` (exposed as `element`) and can keep aggregated results for subsequent steps.  

4. Step may have a "next" attribute. In next attribute it may have a "when" then condition that will route transtion to the next steps.   

# Core Concept V2

NoETL is a lightweight and flexible workflow engine for automating tasks using...

## The main components

1. Playbook is a manifest file of the workflow.
2. Server api provides interface for UI, CLI and Workers
3. Worker pools arranges resources to execute actual tasks of the playbooks.

You describe what do you want in playbooks (YAML file) and NoETL runs it step-by-step (call APIs, run Python, execute SQL, chain other playbooks and a lot of other methods). 

## What a playbook contains?

A playbook has four sections:
1.	metadata – identity and description: name, path, optional version, description.
2.	workload – inputs & knobs: Constants and defaults used by steps. At run time they can be overridden/merged with the payload you pass.
3.	workflow – the flow of steps: The ordered list of steps with transitions, conditions, and loops.
4.	workbook – reusable, named actions: A little library of tasks (e.g., HTTP, Python, DuckDB, Postgres) you can call from workflow steps.

## How to use it?

1.	Write a playbook (.yaml): define inputs, steps, and a library of reusable tasks (workbooks).
2.	Run it from the UI or CLI and pass a payload if needed.
3.	Workers pick up the steps and execute them; you read logs/results and move on.



