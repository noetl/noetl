# Using HTTP in NoETL (Widget-based and Tasks)

Note: The new widget-based DSL lets you call HTTP directly from a step without defining a workbook task. Example:

```yaml
- step: call_api
  type: http
  method: GET
  endpoint: "https://httpbin.org/get"
  headers:
    Authorization: "Bearer {{ env.API_TOKEN }}"
  params:
    id: "{{ workload.id }}"
  as: response
  next: end
```

The rest of this document describes HTTP as a workbook task (supported for backward compatibility).

---

# Using HTTP Tasks with Headers in NoETL

This document explains how to use the HTTP task type with headers in NoETL to make API calls directly without using Python code.

## Overview

The HTTP task type allows you to make HTTP requests directly from your workflow configuration. This is more declarative and often simpler than writing Python code to make the same requests.

Key benefits:
- More declarative approach
- Simpler configuration
- Better separation of concerns
- Easier to maintain and understand

## HTTP Task Structure

A basic HTTP task has the following structure:

```yaml
- name: my_http_task
  type: http
  method: GET  # HTTP method (GET, POST, PUT, DELETE, PATCH)
  endpoint: "https://api.example.com/endpoint"  # API endpoint URL
  headers:  # HTTP headers
    Content-Type: "application/json"
    Authorization: "Bearer {{ api_key }}"
  params:  # Query parameters (for GET requests)
    param1: "value1"
    param2: "value2"
  payload:  # Request body (for POST, PUT, PATCH requests)
    key1: "value1"
    key2: "value2"
  with:  # Variables to use in the task
    api_key: "{{ api_key }}"
  return: |  # Template to format the response
    {% if status == 'success' %}
    {
      "status": "success",
      "data": "{{ result.data }}"
    }
    {% else %}
    {
      "status": "error",
      "message": "API Error: {{ result.error }}"
    }
    {% endif %}
```

## Examples

### 1. Process Natural Language Task (OpenAI API)

This task sends a POST request to the OpenAI API to convert natural language to Amadeus SDK code:

```yaml
- name: process_natural_language_task
  type: http
  method: POST
  endpoint: "https://api.openai.com/v1/chat/completions"
  headers:
    Content-Type: "application/json"
    Authorization: "Bearer {{ openai_api_key }}"
  payload:
    model: "gpt-4o"
    messages:
      - role: "system"
        content: "Your system prompt here..."
      - role: "user"
        content: "{{ query }}"
  with:
    query: "{{ query }}"
    openai_api_key: "{{ openai_api_key }}"
  return: |
    {% if status == 'success' %}
    {
      "status": "success",
      "result": "{{ result.data.choices[0].message.content }}"
    }
    {% else %}
    {
      "status": "error",
      "message": "OpenAI API Error: {{ result.error }}"
    }
    {% endif %}
```

### 2. Execute Amadeus Query Task (Amadeus API)

This task sends a GET request to the Amadeus API:

```yaml
- name: execute_amadeus_query_task
  type: http
  method: GET
  endpoint: "https://test.api.amadeus.com/v1/{{ endpoint_path }}"
  headers:
    Authorization: "Bearer {{ access_token }}"
    Content-Type: "application/json"
  params: "{{ query_params }}"
  with:
    endpoint_path: "{{ endpoint_path }}"
    query_params: "{{ query_params }}"
    access_token: "{{ access_token }}"
  return: |
    {% if status == 'success' %}
    {
      "status": "success",
      "amadeus_response": "{{ result.data.data | tojson }}"
    }
    {% else %}
    {
      "status": "error",
      "message": "Amadeus API Error: {{ result.error }}"
    }
    {% endif %}
```

## Complete Workflow Example

See the `complete_amadeus_workflow_example.yaml` file for a complete example of how to use these HTTP tasks in a workflow.

The workflow demonstrates:
1. Getting the current year
2. Processing a natural language query to Amadeus SDK code
3. Parsing the Amadeus SDK code to extract endpoint and parameters
4. Getting an Amadeus API token
5. Executing the Amadeus API query
6. Processing the Amadeus response to natural language

## Converting Python Tasks to HTTP Tasks

To convert a Python task that makes HTTP requests to an HTTP task:

1. Identify the HTTP method, endpoint, headers, parameters, and payload in the Python code
2. Create an HTTP task with these components
3. Use the `with` section to pass variables to the task
4. Use the `return` section to format the response

For example, this Python code:

```python
import requests

def main(api_key, query):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": query}
        ]
    }
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    response_data = response.json()
    return {
        "status": "success",
        "result": response_data["choices"][0]["message"]["content"]
    }
```

Can be converted to this HTTP task:

```yaml
- name: my_api_task
  type: http
  method: POST
  endpoint: "https://api.openai.com/v1/chat/completions"
  headers:
    Content-Type: "application/json"
    Authorization: "Bearer {{ api_key }}"
  payload:
    model: "gpt-4o"
    messages:
      - role: "user"
        content: "{{ query }}"
  with:
    api_key: "{{ api_key }}"
    query: "{{ query }}"
  return: |
    {% if status == 'success' %}
    {
      "status": "success",
      "result": "{{ result.data.choices[0].message.content }}"
    }
    {% else %}
    {
      "status": "error",
      "message": "API Error: {{ result.error }}"
    }
    {% endif %}
```

## Conclusion

Using HTTP tasks with headers provides a more declarative and maintainable way to make API calls in your workflows. It separates the configuration from the implementation and makes it easier to understand and modify your workflows.