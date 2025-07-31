# Amadeus API Notebook

## Option 1: Local Setup

1. Create and activate a virtual environment.
```
❯ python -m venv .venv
```

2. Activate virtual environment.
```
❯ source .venv/bin/activate
```

3. Install Jupyter in the virtual environment.
```
❯ pip install notebook ipykernel
```

4. Add the virtual environment as a Jupyter kernel.
```
❯ python -m ipykernel install --user --name=${venv_name} --display-name "Python (${venv_name})"
```

5. Export secret values used in Jupyter notebook by simply running `export_secrets.sh`.
```
❯ ./export_secrets.sh
```

## Option 2: Docker Setup

You can run the notebook in a Docker container using the following commands:

```
❯ make build
❯ make up
```

Access the Jupyter notebook at:
```
http://localhost:8899
```

The notebook will be available at: `/home/jovyan/notebooks/amadeus/amadeus-api-notebook.ipynb`

## About the Amadeus API Notebook

The `amadeus-api-notebook.ipynb` interacts with the Amadeus Travel API:

- Authentication with Amadeus API using client credentials
- Converting natural language travel queries to Amadeus API requests using OpenAI
- Executing API calls to the Amadeus endpoints
- Translating API responses back to human-readable format

The notebook provides a complete workflow for travel data queries, from natural language input to formatted results, using the Amadeus API and OpenAI for processing.

Requirements:
- Amadeus API credentials
- OpenAI API key
- Google Cloud Secret Manager setup for securely storing API keys

# NoETL Playbook: Amadeus API Integration with AI

This document provides a detailed explanation of the `amadeus_api_playbook.yaml` NoETL playbook to demonstrate a workflow for integrating with the Amadeus travel API, with AI capabilities from OpenAI.

## Overview

The primary goal of this playbook is to create a "natural language to API" pipeline. It allows a user to submit a travel query in plain English (e.g., "I want a flight from SFO to JFK tomorrow"), and in response, it orchestrates a series of API calls to produce a human-readable summary of flight options.

The entire process is event-driven and logged meticulously in a Postgres database noetl system schema.

### Key Features

- **Natural Language Querying**: Uses OpenAI's GPT-4o model to translate user requests into precise Amadeus API calls.
- **Secure Credential Management**: Fetches API keys and secrets securely from Google Cloud Secret Manager, avoiding hardcoded credentials.
- **Dynamic API Execution**: Executes REST API calls to Amadeus to fetch real-time travel data.
- **AI-Powered Summarization**: Uses OpenAI to convert complex JSON responses from Amadeus into clear, natural language summaries.
- **Comprehensive Logging**: Stores every significant event—API calls, translations, and final results—in structured PostgreSQL tables.
- **Configurable Data Handling**: Includes options to store large text fields (like API responses) as Base64-encoded strings to ensure database compatibility.

## Prerequisites

Before running this playbook, ensure the following are set up:

1.  **NoETL Framework**: The NoETL command-line interface (`noetl`) must be installed and configured.
2.  **PostgreSQL**: A running PostgreSQL instance must be accessible. The playbook will create its own tables (`api_results`, `amadeus_ai_events`). Connection details can be provided via environment variables or will use the defaults specified in the `workload` section.
3.  **Google Cloud Project**: A Google Cloud project with the Secret Manager API enabled.
4.  **API Secrets**: The following secrets must be created in Google Secret Manager within your project:
    - `openai-api-key`: Your API key for OpenAI.
    - `api-key-test-api-amadeus-com`: Your Amadeus API Key (for the test environment).
    - `api-secret-test-api-amadeus-com`: Your Amadeus API Secret (for the test environment).

## Workflow Breakdown

The playbook executes a sequence of steps defined in the `workflow` section. Each step performs a specific task, passing its output to subsequent steps.

| Step | Description | Task Used |
| :--- | :--- | :--- |
| **1. `start`** | Initiates the workflow. | N/A |
| **2. `create_results_table`** | Creates the `api_results` table in PostgreSQL if it doesn't exist. This table stores the final, human-readable output. | `create_results_table_task` |
| **3. `create_amadeus_ai_event_table`** | Creates the `amadeus_ai_events` table if it doesn't exist. This table serves as a detailed audit log for all API interactions. | `create_amadeus_ai_event_table_task` |
| **4. `get_openai_api_key`** | Securely retrieves the OpenAI API key from Google Secret Manager. | `get_openai_api_key_task` |
| **5. `get_amadeus_api_key`** | Securely retrieves the Amadeus API key from Google Secret Manager. | `get_amadeus_api_key_task` |
| **6. `get_amadeus_api_secret`** | Securely retrieves the Amadeus API secret from Google Secret Manager. | `get_amadeus_api_secret_task` |
| **7. `get_amadeus_token`** | Makes a `POST` request to the Amadeus security endpoint to obtain a temporary OAuth2 access token required for subsequent API calls. | `get_amadeus_token_task` |
| **8. `translate_query_to_amadeus`** | This is the first AI-powered step. It sends the user's natural language `query` to the OpenAI Chat Completions API. The system prompt instructs the model to return a JSON object containing the appropriate Amadeus `endpoint` and `params`. | `translate_query_to_amadeus_task` |
| **9. `store_openai_query_event`** | Logs the details of the query translation step (input prompt, raw OpenAI response, status code, duration) into the `amadeus_ai_events` table. | `store_openai_query_event_task` |
| **10. `parse_openai_response`** | Executes a small Python script to parse the JSON content from the OpenAI response. This script is designed to handle cases where the model wraps the JSON in a markdown code block. It extracts the `endpoint` and `params` for the next step. | `parse_openai_response_task` |
| **11. `execute_amadeus_query`** | Makes the actual `GET` request to the Amadeus API. It dynamically constructs the request URL using the `endpoint` from the previous step and attaches the `params` and the `access_token`. | `execute_amadeus_query_task` |
| **12. `store_amadeus_query_event`** | Logs the details of the Amadeus API call (endpoint, parameters, response, status code, duration) into the `amadeus_ai_events` table. | `store_amadeus_query_event_task` |
| **13. `translate_amadeus_response`** | This is the second AI-powered step. It sends the raw, and often complex, JSON response from Amadeus to the OpenAI API. The system prompt instructs the model to summarize the key information into clean, human-readable English. | `translate_amadeus_response_task` |
| **14. `store_openai_response_event`** | Logs the details of the response summarization step into the `amadeus_ai_events` table. | `store_openai_response_event_task` |
| **15. `insert_final_result`** | Inserts the final, user-friendly summary generated by OpenAI into the `api_results` table, linking it with the original query and execution ID. | `insert_final_result_task` |
| **16. `end`** | Marks the successful completion of the workflow. | N/A |

## Configuration Details

The playbook's behavior is defined in the `workload` and `workbook` sections.

### `workload`

This section defines variables and default values for a playbook run.
- `jobId`, `execution_id`: Unique identifiers for the run, generated by NoETL.
- `project_id`: Your Google Cloud Project ID where secrets are stored.
- `query`: The default natural language query to execute. This is overridden by the payload during execution.
- `pg_*`: PostgreSQL connection parameters. These can be overridden by setting environment variables (`POSTGRES_HOST`, `POSTGRES_PORT`, etc.).

### `workbook`

This section defines the reusable tasks that are referenced by the `workflow` steps.

- **`secrets` tasks**: (`get_..._key_task`) Use the `google` provider to fetch secrets by name.
- **`http` tasks**:
    - `get_amadeus_token_task`: Authenticates with Amadeus.
    - `translate_query_to_amadeus_task`: Calls OpenAI to convert the query to an API call. Note the detailed system prompt that guides the AI's output format.
    - `execute_amadeus_query_task`: Calls the Amadeus API with the dynamically determined endpoint and parameters.
    - `translate_amadeus_response_task`: Calls OpenAI to summarize the Amadeus JSON response.
- **`python` task**:
    - `parse_openai_response_task`: A self-contained Python script for robust JSON parsing.
- **`postgres` tasks**:
    - `create_*_table_task`: Use `CREATE TABLE IF NOT EXISTS` for idempotent schema setup.
    - `store_*_event_task` & `insert_final_result_task`: Use `INSERT` statements to log data. They use Jinja templating (`{{ ... }}`) to reference outputs from previous steps (e.g., `{{ translate_query_to_amadeus.data }}`).

## Usage

You can run this playbook using the `noetl` CLI or the provided helper script.

### Using the Helper Script (`playbook`)

The `run_amadeus_api.sh` shell script in the project root simplifies the registration and execution process.

1.  **Make the script executable:**
    ```sh
    chmod +x ./examples/amadeus/run_amadeus_api.sh
    ```

2.  **Run with defaults:**
    ```sh
    ./examples/amadeus/run_amadeus_api.sh 8080 
    ```

3.  **Run with a custom port and query:**
    ```sh
    ./examples/amadeus/run_amadeus_api.sh 8080 "I want a flight from LAX to NYC on December 25, 2025"
    ```

### Manual Execution with `noetl` CLI

1.  **Register the Playbook**: This step uploads the playbook definition to the NoETL server.
    ```sh
    noetl playbooks --register examples/amadeus/amadeus_api_playbook.yaml --port 8080
    ```

2.  **Execute the Playbook**: This triggers a run of the playbook with a specific payload.
    ```sh
    noetl playbooks --execute --path "amadeus/amadeus_api" --payload '{"query": "I want a one-way flight from SFO to JFK on September 15, 2025 for 1 adult"}' --port 8080
    ```

## Database Schema

The playbook creates and populates two tables in your PostgreSQL database.

### `amadeus_ai_events`

This table acts as a detailed audit log.

| Column | Description |
| :--- | :--- |
| `id` | Primary key. |
| `execution_id` | Foreign key linking all events in a single playbook run. |
| `event_type` | A descriptive name for the event (e.g., `openai_query_translation`, `amadeus_api_search`). |
| `api_call_type` | The type of API being called (`openai`, `amadeus`). |
| `input_data` | The JSON payload or parameters sent in the request. |
| `output_data` | The JSON response received from the API. |
| `status_code` | The HTTP status code of the response. |
| `event_time` | Timestamp of when the event was logged. |
| `duration_ms` | The duration of the API call in milliseconds. |
| `details` | Additional metadata, such as the full endpoint URL. |

### `api_results`

This table stores the final, user-facing output.

| Column | Description |
| :--- | :--- |
| `id` | Primary key. |
| `execution_id` | The ID of the playbook run that generated this result. |
| `source` | The source of the result (e.g., `amadeus_api`). |
| `result` | A JSONB object containing the original query and the final natural language summary. |
| `created_at` | Timestamp of when the result was inserted. |

## Customization

This playbook is designed to be a template. You can customize it in several ways:

- **Change AI Behavior**: Modify the `system` prompts in `translate_query_to_amadeus_task` and `translate_amadeus_response_task` to change how the AI interprets requests or formats responses. You could also switch the `model` to a different one (e.g., `gpt-3.5-turbo`).
- **Toggle Base64 Encoding**: In `store_openai_response_event_task` and `insert_final_result_task`, you can set the `encode_as_base64` parameter to `false` if you prefer to store large text/JSON fields directly without encoding.
- **Support More Amadeus Endpoints**: The current OpenAI prompt is trained on flight searches. You can extend its examples to support other Amadeus APIs like hotel searches, points of interest, etc.
- **Adjust `workload` Defaults**: Change the default `project_id` or PostgreSQL connection details to match your environment.