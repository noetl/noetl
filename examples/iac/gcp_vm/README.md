# How to Run the GCP VM Provision Example Playbook

This document explains how to use the GCP VM Provision playbook to create a virtual machine in Google Cloud Platform using REST API calls (without SDK) and track its state in a PostgreSQL database.

## Overview

The GCP VM Provision playbook demonstrates:

1. How to provision a VM in Google Cloud using REST API calls
2. How to track VM creation status and details in a PostgreSQL database
3. How to use DuckDB for data transformation and reporting
4. How to implement a workflow with conditional branching based on operation status

## Prerequisites

Before running this playbook, ensure you have:

1. A Google Cloud Platform account with a project
2. Compute Engine API enabled in your GCP project
3. PostgreSQL database accessible from your NoETL instance
4. NoETL installed and configured

## Playbook Structure

The playbook follows this workflow:

1. Create PostgreSQL tables for tracking VM instances and operations
2. Get GCP access token for API authentication
3. Provision VM using Google Cloud Compute Engine REST API
4. Track VM creation operation in PostgreSQL
5. Poll VM creation status until completion
6. Retrieve VM details after successful creation
7. Store VM details in PostgreSQL
8. Transform VM data using DuckDB for reporting

## Configuration

The playbook accepts the following parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| project_id | GCP project ID | your-gcp-project-id |
| zone | GCP zone for VM creation | us-central1-a |
| machine_type | VM machine type | f1-micro |
| vm_name | Name for the VM | noetl-test-vm |
| pg_host | PostgreSQL host | localhost |
| pg_port | PostgreSQL port | 5432 |
| pg_user | PostgreSQL username | postgres |
| pg_password | PostgreSQL password | postgres |
| pg_db | PostgreSQL database name | noetl |

## Running the Playbook

### Register the Playbook

First, register the playbook with NoETL:

```bash
noetl playbooks --register playbooks/gcp_vm_provision_playbook.yaml --port 8080
```

### Execute the Playbook

Execute the playbook with default parameters:

```bash
noetl playbooks --execute --path "gcp/vm_provision" --port 8080
```

Or with custom parameters:

```bash
noetl playbooks --execute --path "gcp/vm_provision" --port 8080 --payload '{
  "project_id": "your-gcp-project-id",
  "zone": "us-central1-a",
  "machine_type": "f1-micro",
  "vm_name": "test-vm"
}'
```

## Database Schema

The playbook creates two PostgreSQL tables:

### gcp_vm_instances

Stores details about provisioned VMs:

- id: Serial primary key
- execution_id: Unique execution ID
- vm_name: VM instance name
- project_id: GCP project ID
- zone: GCP zone
- machine_type: VM machine type
- status: VM status
- creation_timestamp: When the VM was created
- last_updated: When the record was last updated
- ip_address: VM's IP address
- network: Network configuration
- cpu_platform: CPU platform
- disk_size_gb: Boot disk size
- disk_type: Boot disk type
- metadata: VM metadata as JSONB
- labels: VM labels as JSONB
- raw_details: Complete VM details as JSONB

### gcp_vm_operations

Tracks VM operations:

- id: Serial primary key
- execution_id: Unique execution ID
- operation_id: GCP operation ID
- operation_type: Type of operation
- target_vm: Target VM name
- status: Operation status
- start_time: When the operation started
- end_time: When the operation completed
- error_message: Error message if failed
- raw_response: Complete operation details as JSONB

## Output

The playbook produces:

1. PostgreSQL records in the gcp_vm_instances and gcp_vm_operations tables
2. A CSV file with VM summary information at /tmp/vm_summary_[execution_id].csv

## Notes

- This playbook uses a simulated access token for demonstration purposes. In a production environment, you would need to implement proper authentication.
- The smallest machine type in GCP is f1-micro, which is used as the default.
- The playbook includes error handling for failed VM creation.
- All VM details are stored in PostgreSQL for tracking and auditing.