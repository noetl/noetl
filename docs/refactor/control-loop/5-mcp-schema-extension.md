# MCP Schema Extension for Playbooks

Objective: Extend the Playbook YAML to support the Model Context Protocol (MCP) concepts. We do not embed an MCP SDK; we express the MCP interaction declaratively and translate it into NoETL steps and tasks.

Background (MCP gist):
- MCP defines a way to structure model interactions with tool calls, resources, and conversational turns. We map these to playbook constructs so the broker/worker can execute them via existing plugins/utils.

Top-level additions (playbook YAML):

mcp:
  models:
    - name: gpt-4o
      provider: openai
      params:
        temperature: 0.2
  tools:
    - name: search_docs
      type: http               # map to existing plugin types (http/python/postgres/duckdb)
      spec:
        method: GET
        url: https://search/api?q={{ input.query }}
  resources:
    - name: kb_articles
      type: postgres
      spec:
        dsn: {{ secrets.pg_dsn }}
        sql: SELECT id, title, body FROM kb WHERE topic = {{ input.topic }}
  prompts:
    - name: summarize
      template: |
        Summarize the following text:
        {{ input.text }}
  turns:
    - name: t1
      model: gpt-4o
      system: You are a helpful assistant.
      user:
        - use: resource:kb_articles       # binds resource result to the context of this turn
        - text: "What are key points?"
      tools_allowed: [search_docs]
      save: { storage: event_log }

Design notes:
- mcp.models: named model presets; used by turns.
- mcp.tools/resources: wrappers that map to existing plugin capabilities. Execution happens as normal NoETL tasks; their results are made available to turns.
- mcp.prompts: reusable prompt templates.
- mcp.turns: a sequence of “LLM calls” that can optionally invoke tools and consume resources. Each turn materializes into one or more steps in the workflow section.

Workflow generation patterns:
- Each mcp.turn becomes a synthetic step of type: workbook or type: python/http that:
  - Renders its inputs from resources and prior steps.
  - When tools_allowed present, the step may branch to tool-execution steps and then return to the model step with the tool outputs as additional context.
- Minimal viable translation keeps control explicit: mcp.turn → a named step with:

workflow:
  - step: start
    next: [ mcp_t1 ]
  - step: mcp_t1
    type: workbook
    task:
      name: model_call
      type: http               # example using HTTP gateway for LLM
      url: {{ secrets.llm_gateway }}/chat
      method: POST
      headers:
        Authorization: Bearer {{ secrets.llm_token }}
      data:
        model: {{ mcp.models.gpt-4o.name }}
        system: "You are a helpful assistant."
        messages:
          - role: user
            content: {{ prompts.summarize.template | render({ input: context.input }) }}
        tools_allowed: {{ mcp.turns.t1.tools_allowed }}
    save:
      storage: event_log

Schema validation rules:
- mcp.models[*].name: required string; provider optional; params optional map.
- mcp.tools/resources[*]: require name, type (mapped to an existing plugin), spec (plugin config). Names must be unique within their section.
- mcp.prompts[*]: name and template required (string or structured template).
- mcp.turns[*]: name, model (reference), user (array of inputs: text or use:resource:<name>), optional tools_allowed (array of tool names), optional save.

Execution mapping rules:
- Resource declarations compile into hidden steps that run before their first use, or are inlined via server-side rendering if read-only and safe.
- Tool calls compile into explicit steps between turns (iterator if multiple invocations are needed); their results merge into turn context.
- The final turn’s result maps to the playbook’s end result; if save is present, it persists according to save_result.md.

Compatibility note:
- This v2 refactor is not backward compatible. MCP constructs are first-class in the new schema. Legacy playbooks may require explicit migration to the v2 schema and semantics; mixing classic steps may not be supported without migration.

Base v2 schema requirements (also apply to MCP playbooks):
- metadata.path and metadata.name are mandatory and used for catalog linkage.
- workload defines baseline variables (overridable via transitions/payloads).
- workbook is a list of named actions; workflow steps reference them using `type: workbook` + `task: <name>` when invoking a declared action.

Open questions / options:
- Provide a built-in “llm” plugin vs. require an HTTP gateway; start with HTTP to avoid runtime coupling.
- Tool execution in-loop vs. serial; start serial; add concurrency later via iterator or explicit fanout.

Acceptance criteria for MCP support (docs + validation + examples):
- YAML schema additions documented and examples compile into valid steps.
- Validation errors are clear for unresolved references (model/tool/resource/prompt names).
- End-to-end example using a resource + tool + turn runs through enqueue→lease→execute→emit→complete with observable events.
