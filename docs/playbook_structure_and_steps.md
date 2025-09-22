# Playbook structure

## Metadata

Every playbook is a YAML doc with a fixed header plus three main blocks.
```YAML
# Header
apiVersion: noetl.io/v1
kind: Playbook
name: name_of_playbook
path: path/to/catalog
version: "0.1.0"
description: description of playbook

# Main blocks
workload: <input params>
workflow: <step structure>

# Optional block
workbook: <taks calls from steps>
```

## Workload

A flat map of inputs. These are read only and referenced via Jinja2.
```YAML
workload:
  jobId: "{{ job.uuid }}"

  # Take value from env file
  pg_host: "{{ env.POSTGRES_HOST | default('localhost') }}"
  pg_port: "{{ env.POSTGRES_PORT | default('5432') }}"
  pg_user: "{{ env.POSTGRES_USER | default('postgres') }}"
  pg_password: "{{ env.POSTGRES_PASSWORD | default('postgres') }}"
  pg_db: "{{ env.POSTGRES_DB | default('noetl') }}"
  cities:
    - name: "London"
      lat: 51.51
      lon: -0.13
    - name: "Paris"
      lat: 48.85
      lon: 2.35
  base_url: "https://api.open-meteo.com/v1" 
```

## Workflow

Workflow is an ordered list of steps. All steps are isolated, you have to pass data forward explicitly. Each step may include:
- desc - description of a step
- type - step kind
- with - local input
- next - transition
- pass - boolean/template to skip

How data flows:
- with: sets the local context 
- a result of a step could be reach with `step_name.result`
- _how to get a result of a loop?_

Control flow:
- next routes by conditions with wnen/else
- pass pairs with workload steps to skip
- _how to work with override?_

```YAML
# need an example of YANL workflow where all steps uses
```

## Workbook

# Steps overview

## Step types

-	start — Entry point of a workflow. Must route to the first executable step via next.
-	end — Terminal step. No next. Used broadly.
-	workbook — Invokes a named task from the workbook library; use task: and with: to pass inputs.
-	python — Runs inline Python in the step itself.
-	http — Makes an HTTP call directly from a step (method, endpoint, headers, params/payload).  ￼
-	duckdb — Executes DuckDB SQL/script in the step.
-	postgres — Executes PostgreSQL SQL/script in the step.
-	secrets — Reads a secret from a provider (e.g., Google Secret Manager) and exposes it as secret_value.
-	playbooks — Executes all playbooks under a catalog path, forwarding inputs via with:; the step result can be passed on to the next step.
- loop - Run the loop over the workbook (if you need to loop one step) or the playbook (if need to loop two or more steps)
- _other steps?_

## Python step

Python step can execute some python code. 
- Entry point is a function named `main(...)` defined in a code block.
- Input is a whatever you put under the step's with and refernced via Jinja2.
- Output is the return value of the main function in a code block, can be accessed in the next steps via `step_name.some_return`
```YAML
- step: step_name
  type: python
  desc: description
  # input for the step
  with: 
    some_input: "{{ input }}"
    another_input: "{{ another input }}"
  # python code block
  code: |
  # starts with `main` function
    def main(some_input, another_input):
        # python code
        return {...}
  next:
```
- _how to use some help functions in the main, and what if I want to call help function in the multiple steps?_
- _how to use several python functions in one code block?_

## DuckDB step

Runs DuckDB SQL statement inside the workflow step.
- Input is a whatever you put under the step's with and refernced via Jinja2.
- _how to return from the duckdb step?_
- you have to install needed DuckDB extensions once per every step.
- attaches to external databases also have to be defined in every step where conection is in usage.

```YAML
- step: step_nmae
  type: duckdb
  desc: description
  with: 
    some_input: "{{ inputs for templating }}"
  command: |  

    # connection to external postgres database if needed

    INSTALL postgres; LOAD postgres;

    ATTACH 'host={{ host }} port={{ port }} user={{ user }} password={{ password }} dbname={{ db }}' AS pgdb (TYPE POSTGRES);

    # DuckDB SQL code 
```