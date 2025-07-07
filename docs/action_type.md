# NoETL Workflow Tasks Guide

This guide provides detailed information about the available tasks in NoETL and their parameters.

## Overview

NoETL provides a variety of built-in tasks for common operations, such as HTTP requests, database operations, file operations, data transformations, and notifications. Tasks are used in the workflow section of a playbook to define the steps of the workflow.

## Task Structure

A task step in a NoETL playbook has the following structure:

```yaml
- step: step_name
  call:
    name: step_name
    type: task_type
    with:
      param1: value1
      param2: value2
  next:
    - step: next_step
```

- **step**: A unique name for the step
- **call**: Indicates this is a task call
- **name**: The name of the task
- **type**: The type of task to perform (e.g., `http`, `secret`, `postgres`, `duckdb`, `workbook`, `playbook`)
- **with**: Parameters for the task
- **next**: The next step to execute after this task

## HTTP Tasks

HTTP tasks allow you to interact with web APIs and services.

### http.get

Fetches data from a URL using the HTTP GET method.

**Parameters:**

- **url** (string, required): The URL to fetch data from
- **params** (object, optional): Query parameters to include in the URL
- **headers** (object, optional): HTTP headers to include in the request
- **timeout** (number, optional): Request timeout in seconds (default: 30)
- **verify** (boolean, optional): Whether to verify SSL certificates (default: true)

**Example:**

```yaml
- step: fetch_data
  call:
    name: fetch_data
    type: http
    method: GET
    endpoint: "https://api.example.com/data"
    params:
      id: "{{ workload.id }}"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
    timeout: 60
    verify: true
  next:
    - step: process_data
```

### http.post

Sends data to a URL using the HTTP POST method.

**Parameters:**

- **url** (string, required): The URL to send data to
- **data** (object/string, optional): Data to include in the request body
- **json** (object, optional): JSON data to include in the request body
- **params** (object, optional): Query parameters to include in the URL
- **headers** (object, optional): HTTP headers to include in the request
- **timeout** (number, optional): Request timeout in seconds (default: 30)
- **verify** (boolean, optional): Whether to verify SSL certificates (default: true)

**Example:**

```yaml
- step: create_resource
  call:
    name: create_resource
    type: http
    method: POST
    endpoint: "https://api.example.com/resources"
    json:
      name: "{{ workload.resource_name }}"
      description: "{{ workload.resource_description }}"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
      Content-Type: "application/json"
  next:
    - step: process_response
```

### http.put

Updates data at a URL using the HTTP PUT method.

**Parameters:**

- **url** (string, required): The URL to update data at
- **data** (object/string, optional): Data to include in the request body
- **json** (object, optional): JSON data to include in the request body
- **params** (object, optional): Query parameters to include in the URL
- **headers** (object, optional): HTTP headers to include in the request
- **timeout** (number, optional): Request timeout in seconds (default: 30)
- **verify** (boolean, optional): Whether to verify SSL certificates (default: true)

**Example:**

```yaml
- step: update_resource
  call:
    name: update_resource
    type: http
    method: PUT
    endpoint: "https://api.example.com/resources/{{ workload.resource_id }}"
    json:
      name: "{{ workload.resource_name }}"
      description: "{{ workload.resource_description }}"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
      Content-Type: "application/json"
  next:
    - step: process_response
```

### http.delete

Deletes data at a URL using the HTTP DELETE method.

**Parameters:**

- **url** (string, required): The URL to delete data at
- **params** (object, optional): Query parameters to include in the URL
- **headers** (object, optional): HTTP headers to include in the request
- **timeout** (number, optional): Request timeout in seconds (default: 30)
- **verify** (boolean, optional): Whether to verify SSL certificates (default: true)

**Example:**

```yaml
- step: delete_resource
  call:
    name: delete_resource
    type: http
    method: DELETE
    endpoint: "https://api.example.com/resources/{{ workload.resource_id }}"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
  next:
    - step: process_response
```

## Database Tasks

Database tasks allow you to interact with databases.

### db.query

Executes a SQL query and returns the results.

**Parameters:**

- **connection** (string, required): Database connection string or connection name
- **query** (string, required): SQL query to execute
- **params** (object/array, optional): Parameters for the query

**Example:**

```yaml
- step: query_data
  call:
    name: query_data
    type: postgres
    with:
      db_host: "{{ workload.db_host }}"
      db_port: "{{ workload.db_port }}"
      db_user: "{{ workload.db_user }}"
      db_password: "{{ workload.db_password }}"
      db_name: "{{ workload.db_name }}"
    command: |
      SELECT * FROM users WHERE id = {{ workload.user_id }}
  next:
    - step: process_data
```

### db.execute

Executes a SQL statement that doesn't return results (e.g., INSERT, UPDATE, DELETE).

**Parameters:**

- **connection** (string, required): Database connection string or connection name
- **statement** (string, required): SQL statement to execute
- **params** (object/array, optional): Parameters for the statement

**Example:**

```yaml
- step: update_data
  call:
    name: update_data
    type: postgres
    with:
      db_host: "{{ workload.db_host }}"
      db_port: "{{ workload.db_port }}"
      db_user: "{{ workload.db_user }}"
      db_password: "{{ workload.db_password }}"
      db_name: "{{ workload.db_name }}"
    command: |
      UPDATE users SET name = '{{ workload.user_name }}' WHERE id = {{ workload.user_id }}
  next:
    - step: process_result
```

### db.insert

Inserts data into a table.

**Parameters:**

- **connection** (string, required): Database connection string or connection name
- **table** (string, required): Table to insert data into
- **data** (object/array, required): Data to insert

**Example:**

```yaml
- step: insert_data
  call:
    name: insert_data
    type: postgres
    with:
      db_host: "{{ workload.db_host }}"
      db_port: "{{ workload.db_port }}"
      db_user: "{{ workload.db_user }}"
      db_password: "{{ workload.db_password }}"
      db_name: "{{ workload.db_name }}"
    command: |
      INSERT INTO users (name, email, created_at)
      VALUES ('{{ workload.user_name }}', '{{ workload.user_email }}', NOW())
  next:
    - step: process_result
```

### db.update

Updates data in a table.

**Parameters:**

- **connection** (string, required): Database connection string or connection name
- **table** (string, required): Table to update data in
- **data** (object, required): Data to update
- **where** (object, required): Conditions for the update

**Example:**

```yaml
- step: update_data
  call:
    name: update_data
    type: postgres
    with:
      db_host: "{{ workload.db_host }}"
      db_port: "{{ workload.db_port }}"
      db_user: "{{ workload.db_user }}"
      db_password: "{{ workload.db_password }}"
      db_name: "{{ workload.db_name }}"
    command: |
      UPDATE users 
      SET name = '{{ workload.user_name }}', updated_at = NOW() 
      WHERE id = {{ workload.user_id }}
  next:
    - step: process_result
```

### db.delete

Deletes data from a table.

**Parameters:**

- **connection** (string, required): Database connection string or connection name
- **table** (string, required): Table to delete data from
- **where** (object, required): Conditions for the delete

**Example:**

```yaml
- step: delete_data
  call:
    name: delete_data
    type: postgres
    with:
      db_host: "{{ workload.db_host }}"
      db_port: "{{ workload.db_port }}"
      db_user: "{{ workload.db_user }}"
      db_password: "{{ workload.db_password }}"
      db_name: "{{ workload.db_name }}"
    command: |
      DELETE FROM users 
      WHERE id = {{ workload.user_id }}
  next:
    - step: process_result
```

## File Tasks

File tasks allow you to interact with the file system.

### file.read

Reads data from a file.

**Parameters:**

- **path** (string, required): Path to the file
- **format** (string, optional): Format of the file (json, yaml, csv, text)
- **encoding** (string, optional): Encoding of the file (default: utf-8)

**Example:**

```yaml
- step: read_file
  call:
    name: read_file
    type: file
    with:
      operation: "read"
      path: "{{ workload.file_path }}"
      format: "json"
      encoding: "utf-8"
  next:
    - step: process_data
```

### file.write

Writes data to a file.

**Parameters:**

- **path** (string, required): Path to the file
- **data** (any, required): Data to write
- **format** (string, optional): Format of the file (json, yaml, csv, text)
- **encoding** (string, optional): Encoding of the file (default: utf-8)
- **mode** (string, optional): File mode (w, a, default: w)

**Example:**

```yaml
- step: write_file
  call:
    name: write_file
    type: file
    with:
      operation: "write"
      path: "{{ workload.output_path }}"
      data: "{{ process_data.result }}"
      format: "json"
      encoding: "utf-8"
      mode: "w"
  next:
    - step: notify_user
```

### file.append

Appends data to a file.

**Parameters:**

- **path** (string, required): Path to the file
- **data** (any, required): Data to append
- **format** (string, optional): Format of the file (json, yaml, csv, text)
- **encoding** (string, optional): Encoding of the file (default: utf-8)

**Example:**

```yaml
- step: append_file
  call:
    name: append_file
    type: file
    with:
      operation: "append"
      path: "{{ workload.log_path }}"
      data: "{{ process_data.result }}"
      format: "text"
      encoding: "utf-8"
  next:
    - step: notify_user
```

### file.delete

Deletes a file.

**Parameters:**

- **path** (string, required): Path to the file

**Example:**

```yaml
- step: delete_file
  call:
    name: delete_file
    type: file
    with:
      operation: "delete"
      path: "{{ workload.temp_file_path }}"
  next:
    - step: notify_user
```

## Data Transformation Tasks

Data transformation tasks allow you to transform data.

### transform.map

Applies a function to each item in a list.

**Parameters:**

- **data** (array, required): List of items to transform
- **function** (string, required): Function to apply to each item

**Example:**

```yaml
transform_data:
  call:
    name: transform_data
    type: python
    with:
      data: "{{ fetch_data.response.json.items }}"
    code: |
      def main(data):
          return [{"price": item["price"] * 1.1, **{k: v for k, v in item.items() if k != "price"}} for item in data]
  next: save_data
```

### transform.filter

Filters items in a list.

**Parameters:**

- **data** (array, required): List of items to filter
- **condition** (string, required): Condition to filter by

**Example:**

```yaml
filter_data:
  call:
    name: filter_data
    type: python
    with:
      data: "{{ fetch_data.response.json.items }}"
      min_price: 10
    code: |
      def main(data, min_price):
          return [item for item in data if item["price"] > min_price]
  next: save_data
```

### transform.reduce

Reduces a list to a single value.

**Parameters:**

- **data** (array, required): List of items to reduce
- **function** (string, required): Function to apply to each item
- **initial** (any, optional): Initial value for the reduction

**Example:**

```yaml
calculate_total:
  call:
    name: calculate_total
    type: python
    with:
      data: "{{ fetch_data.response.json.items }}"
    code: |
      def main(data):
          return sum(item["price"] for item in data)
  next: save_data
```

### transform.merge

Merges multiple objects or lists.

**Parameters:**

- **objects** (array, required): Objects or lists to merge

**Example:**

```yaml
merge_data:
  call:
    name: merge_data
    type: python
    with:
      data1: "{{ fetch_data_1.response.json }}"
      data2: "{{ fetch_data_2.response.json }}"
    code: |
      def main(data1, data2):
          if isinstance(data1, list) and isinstance(data2, list):
              return data1 + data2
          elif isinstance(data1, dict) and isinstance(data2, dict):
              return {**data1, **data2}
          else:
              return [data1, data2]
  next: save_data
```

## Notification Tasks

Notification tasks allow you to send notifications.

### notify.email

Sends an email.

**Parameters:**

- **to** (string/array, required): Recipient email address(es)
- **subject** (string, required): Email subject
- **body** (string, required): Email body
- **from** (string, optional): Sender email address
- **cc** (string/array, optional): CC email address(es)
- **bcc** (string/array, optional): BCC email address(es)
- **attachments** (array, optional): Attachments

**Example:**

```yaml
send_email:
  call:
    name: send_email
    type: email
    with:
      to: "{{ workload.user_email }}"
      subject: "Data Processing Complete"
      body: "Your data has been processed successfully."
      from: "noreply@example.com"
      cc: "support@example.com"
      attachments:
        - path: "{{ workload.output_path }}"
          name: "processed_data.json"
  next: end
```

### notify.slack

Sends a Slack message.

**Parameters:**

- **webhook** (string, required): Slack webhook URL
- **message** (string, required): Message to send
- **channel** (string, optional): Channel to send the message to
- **username** (string, optional): Username to send the message as
- **icon_emoji** (string, optional): Emoji to use as the icon
- **attachments** (array, optional): Slack message attachments

**Example:**

```yaml
send_slack:
  call:
    name: send_slack
    type: slack
    with:
      webhook: "{{ workload.slack_webhook }}"
      message: "Data processing complete"
      channel: "#notifications"
      username: "NoETL Bot"
      icon_emoji: ":robot_face:"
      attachments:
        - title: "Processing Results"
          text: "{{ process_data.result }}"
          color: "good"
  next: end
```

### notify.webhook

Sends a webhook notification.

**Parameters:**

- **url** (string, required): Webhook URL
- **data** (object, required): Data to send
- **method** (string, optional): HTTP method (default: POST)
- **headers** (object, optional): HTTP headers

**Example:**

```yaml
send_webhook:
  call:
    name: send_webhook
    type: http
    method: POST
    endpoint: "{{ workload.webhook_url }}"
    json:
      event: "data_processing_complete"
      result: "{{ process_data.result }}"
    headers:
      Content-Type: "application/json"
      Authorization: "Bearer {{ workload.webhook_token }}"
  next: end
```

## Console Tasks

Console tasks allow you to print messages to the console.

### console.print

Prints a message to the console.

**Parameters:**

- **message** (string, required): Message to print

**Example:**

```yaml
print_message:
  call:
    name: print_message
    type: python
    with:
      user_name: "{{ workload.user_name }}"
    code: |
      def main(user_name):
          message = f"Processing data for {user_name}"
          print(message)
          return {"message": message}
  next: process_data
```

## Next Steps

- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [Examples](examples.md) - See more examples of NoETL playbooks
