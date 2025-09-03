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

3. Step may has a loop attribute. In that case it will execute action type that it has for each item of the loop definition and keep aggregated result as a reference for the next steps.  

4. Step may have a "next" attribute. In next attribute it may have a "when" then condition that will route transtion to the next steps.   


