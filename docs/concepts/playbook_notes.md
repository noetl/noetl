# Playbook structure notes
## Working examples:

- tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml
- tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml
- tests/fixtures/playbooks/playbook_composition/playbook_composition.yaml
- tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml

## main concept:
1. Technically, we use jinja2 template rendering to substitute variables and context data.
2. Playbook must have a metadata section with name and path.
3. Workload is a section to define global variables, and it will be merged with payload input when a request for execution is registered.
4. Workbook is a section when we keep named tasks (a task is based on an action type) that we can refer from the workflow section where we define steps.
5. The workflow section has a list of steps that use the "next" attribute to define tradition to one or many other steps.
6. The workflow section must have a step named "start" it's a special type of task that do routing to other steps and is an entry point for the workflow execution.
7. step attribute of a step defines the name of the step.
8. a step can have desc attribute for description of what a step does.
9. step must have an attribute type that defines what type of action it has to perform.
10. Type of actions are:
11. type: workbook reference to the workbook section, in that case a step must have an attribute name by which the engine will look up for the task (action type) to be executed.
12. step can have an action type: workbook, or any other type that workbook can have for named action types. Except the type: workbook, the workbook can have the rest of the type declared for tasks as a step can have. The difference is that a step can have a type: workbook in addition to that.
13. type: python defines an action type to execute python code that is defined in the "code" attribute. Nuance here is that actual code should be a main function `def main(input_data):` with arguments that will be passed to that action type using "data" attribute.
14. the action type of the step can be also "playbook", in that case step passes to the playbook data and waits for its execution to be completed.
15. action type can be `type: iterator` in that case step should have attributes
``` yaml
collection: "{{ workload.users }}"
element: user
mode: sequential
task:
```
and it will execute the task fpr each element of the collection.
16. Each task (action type) can have a "save" attribute that will be used to call another action type that can handle storage like "psotgres", "duckdb", "http" and pass a result of execution of the task to the action type defined in the "save" attribute.
17. Each step and only step can have the attribute "next" and in "next" it might be an attribute "when" that contains condition and "then" attribute with a list of steps to be jumped to:
``` yaml
- step: start
  desc: Start Weather Analysis Workflow
  next:
  - when: '{{ workload.state == ''ready'' }}'
    then:
    - step: city_loop
  - else:
    - step: end
```
also we can pass different data to the next step using the "data" attribute:
```yaml
  next:
  - data:
      alerts: '{{ city_loop.results }}'
    step: aggregate_alerts
```

18. Action type can have attribute “auth” - describe options.
19. Action can return a result, we need to be able to declare what we save using the “save” attribute of an action type, and what we return and keep as a result of execution of an action type, making it available for other steps by reference.
20. A step named "end" has to be defined to allow aggregating playbook execution and save a result based on conditions or to pass it back to the parent playbook. 
