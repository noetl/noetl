---
sidebar_position: 4
title: Message Learning
description: Event learning and message learning concepts for business task automation with human-in-the-loop
---

# Message Learning & Event-Driven Orchestration

NoETL implements a message learning architecture for continuous workflow optimization through event-driven feedback loops.

![NoETL Message Learning Architecture](/img/noetl-message-learning-architecture-overview.jpg)

## Event Learning Concept

**Event learning** enables NoETL workflows to improve over time by capturing execution patterns, outcomes, and human decisions as structured events:

- **Execution Events**: Every workflow step emits start/finish/error events with timing and metadata
- **Decision Events**: Human approvals, overrides, and interventions captured as first-class events
- **Feedback Loops**: Downstream system responses fed back into workflow optimization
- **Pattern Recognition**: AI models analyze event streams to detect anomalies and suggest improvements

## Message Learning Architecture

The message learning system operates as a control loop:

1. **Business Task Execution**: Workflows process domain-specific tasks (data pipelines, ML training, API integrations)
2. **Event Capture**: All execution state persisted to event log with full context
3. **Human-in-the-Loop**: Decision points where domain experts review, approve, or override automated actions
4. **Learning Layer**: Vector embeddings and semantic search enable AI assistants to:
   - Suggest workflow optimizations based on past executions
   - Recommend error recovery strategies from similar failures
   - Auto-tune retry policies and resource allocation
   - Generate new playbooks from natural language descriptions

## Control Loop Components

### 1. Event Bus (PostgreSQL + ClickHouse)

All workflow execution state stored as immutable events:

```sql
SELECT execution_id, step_name, status, duration_ms, error_message
FROM noetl.event
WHERE playbook_path = 'data/ingestion/daily_load'
ORDER BY created_at DESC;
```

Events exported to ClickHouse for analytics and AI agent access via MCP server.

### 2. Human Decision Points

Workflows can pause for human review using conditional routing:

```yaml
workflow:
  - step: validate_data_quality
    tool:
      kind: python
      code: |
        # Check data quality metrics
        result = {"quality_score": 0.85, "anomalies": 12}
    next:
      - when: "{{ validate_data_quality.quality_score < 0.9 }}"
        then:
          - step: await_human_approval  # Pause for review
        args:
          issue: "Data quality below threshold"
          
  - step: await_human_approval
    tool:
      kind: http
      method: POST
      url: "{{ workflow_approval_service }}/requests"
    # Execution pauses until approval received via callback
```

### 3. Feedback Collection

Capture outcomes and human decisions:

```yaml
- step: record_decision
  tool:
    kind: postgres
    table: execution_decisions
    data:
      execution_id: "{{ execution_id }}"
      decision_maker: "{{ current_user }}"
      action: "{{ vars.approval_action }}"
      reasoning: "{{ vars.approval_comment }}"
      timestamp: "{{ now() }}"
```

### 4. AI-Assisted Optimization

Vector search over execution history enables:

- **Semantic Playbook Search**: Find similar workflows by natural language description
- **Error Resolution**: Retrieve past solutions for similar failures
- **Parameter Tuning**: Recommend optimal retry policies, timeouts, resource limits
- **Auto-Generation**: Create new playbooks from examples and documentation

Example query via ClickHouse MCP:

```python
# Find similar failed executions for error recovery
similar_failures = clickhouse_mcp.query(
    query="""
    SELECT execution_id, playbook_path, error_message, resolution
    FROM observability.noetl_events
    WHERE status = 'failed' 
      AND similarity(error_embedding, %(current_error_embedding)s) > 0.8
    ORDER BY created_at DESC
    LIMIT 5
    """,
    params={"current_error_embedding": embed(current_error)}
)
```

## Business Task Automation Patterns

### 1. Data Pipeline Orchestration

ETL/ELT workflows with quality gates:

- Ingest data from sources
- Transform and validate
- Human review for anomalies
- Load to warehouse
- Capture feedback for future anomaly detection

### 2. MLOps Lifecycle

Model training with experiment tracking:

- Feature engineering
- Model training with hyperparameter tuning
- Validation against production baselines
- Human approval for deployment
- A/B test results fed back for next iteration

### 3. API Integration Workflows

Multi-step API orchestration with retry logic:

- Fetch data from external APIs
- Transform and enrich
- Conditional routing based on response patterns
- Adaptive retry strategies learned from past failures

## Benefits of Message Learning

1. **Continuous Improvement**: Workflows get smarter over time without code changes
2. **Domain Knowledge Capture**: Human decisions preserved as structured data
3. **Explainability**: Full audit trail of automated and manual actions
4. **AI-Native**: Semantic search and LLM reasoning natively integrated
5. **Resilience**: Learn from failures to prevent future issues

## Observability Stack Integration

Message learning leverages NoETL's observability stack:

- **ClickHouse**: Event storage and analytics queries
- **Qdrant**: Vector embeddings for semantic search
- **NATS**: Real-time event streaming for instant feedback
- **VictoriaMetrics**: Time-series metrics for performance analysis
- **Grafana**: Dashboard visualization of execution patterns

See [Observability Services](/docs/observability/overview) for complete integration details.

## Next Steps

- [Playbook Structure](/docs/features/playbook_structure) - Learn the DSL syntax
- [Event API](/docs/reference/api/event) - Programmatic event access
- [Observability](/docs/observability/overview) - Analytics stack setup
- [AI-Native Features](/docs/getting-started/semantic-pipeline) - Semantic search capabilities
