---
sidebar_position: 10
title: Transfer Tool
description: Bulk data transfer between sources and targets
---

# Transfer Tool

The transfer tool provides declarative bulk data movement between sources and targets with automatic field mapping.

## Overview

Unlike manual Python transformation or iterators, the transfer tool:
- Fetches data from source (HTTP, database)
- Automatically maps and transforms fields
- Inserts directly into target with schema mapping
- Handles the entire ETL pipeline in a single step

## Basic Usage

```yaml
- step: transfer_data
  tool: transfer
  source:
    type: http
    url: "https://api.example.com/data"
    method: GET
  target:
    type: postgres
    auth: "{{ workload.pg_auth }}"
    table: public.my_table
    mode: insert
  mapping:
    target_col1: source_field1
    target_col2: source_field2
```

## Source Configuration

### HTTP Source

```yaml
source:
  type: http
  url: "{{ workload.api_url }}"
  method: GET
  headers:
    Authorization: "Bearer {{ keychain.api_token }}"
```

### PostgreSQL Source

```yaml
source:
  type: postgres
  auth: "{{ workload.source_db }}"
  query: "SELECT * FROM source_table WHERE updated_at > '{{ workload.since }}'"
```

### Snowflake Source

```yaml
source:
  type: snowflake
  auth: "{{ workload.snowflake_auth }}"
  query: |
    SELECT customer_id, name, email
    FROM customers
    WHERE region = '{{ workload.region }}'
```

## Target Configuration

### PostgreSQL Target

```yaml
target:
  type: postgres
  auth: "{{ workload.pg_auth }}"
  table: public.destination_table
  mode: insert  # insert | upsert | truncate_insert
  mapping:
    id: customer_id
    full_name: name
    email_address: email
```

### Target Modes

| Mode | Description |
|------|-------------|
| `insert` | Append rows to table |
| `upsert` | Insert or update on conflict (requires primary key) |
| `truncate_insert` | Truncate table before inserting |

### Snowflake Target

```yaml
target:
  type: snowflake
  auth: "{{ workload.snowflake_auth }}"
  table: ANALYTICS.PUBLIC.CUSTOMERS
  mode: insert
  mapping:
    CUSTOMER_ID: id
    CUSTOMER_NAME: name
```

## Field Mapping

The `mapping` block specifies how source fields map to target columns:

```yaml
mapping:
  target_column: source_field     # Direct mapping
  user_id: userId                 # Rename field
  created_at: null                # Use database default
```

### Nested Field Access

Access nested JSON fields with dot notation:

```yaml
mapping:
  city: address.city
  zip: address.postal_code
  country: address.country.name
```

## Complete Example

HTTP API to PostgreSQL transfer:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: http_to_postgres_transfer
  path: data_transfer/http_to_postgres_transfer

workload:
  api_url: "https://jsonplaceholder.typicode.com/posts"
  pg_auth: pg_demo

workflow:
  - step: start
    next:
      - step: create_table

  - step: create_table
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      DROP TABLE IF EXISTS public.posts;
      CREATE TABLE public.posts (
        id SERIAL PRIMARY KEY,
        post_id INTEGER,
        user_id INTEGER,
        title TEXT,
        body TEXT,
        fetched_at TIMESTAMPTZ DEFAULT NOW()
      );
    next:
      - step: transfer_data

  - step: transfer_data
    tool: transfer
    source:
      type: http
      url: "{{ workload.api_url }}"
      method: GET
    target:
      type: postgres
      auth: "{{ workload.pg_auth }}"
      table: public.posts
      mode: insert
    mapping:
      post_id: id
      user_id: userId
      title: title
      body: body
    next:
      - step: verify

  - step: verify
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    query: "SELECT COUNT(*) as total FROM public.posts"
    next:
      - step: end

  - step: end
```

## Working Examples

Complete transfer playbooks in the repository:
- [http_to_postgres_transfer/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer)
- [snowflake_postgres/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/data_transfer/snowflake_postgres)
