# NoETL mini-micro-service architecture

1. Command API service:
- Exposes an API endpoint to receive commands from external clients.
- Validates and registers commands in the local file-based database.
- Provides endpoints for querying and managing commands.

2. Event API service:
- Exposes an API endpoint to provide event data.
- Receives events from the workflow engine.
- Writes events to the local file-based event log database.
- Provides endpoints for querying and subscribing to events.

3. Dispatcher API service:
- Exposes an API endpoint to trigger dispatching actions.
- Subscribes to the Event API for relevant events.
- Schedules new commands based on event data.
- Manages task queues for executing scheduled commands.
- Communicates with task workers.

4. Task Workers:
- Workers that execute scheduled commands.
- Retrieve commands from the Dispatcher API.
- Execute task steps and write events to the Event API.
- Handle retries and error management.

5. Local Storage:
- Use a structured directory and file approach to store commands and events, grouped by workflow ID.
- Commands and Events are stored as binary files.

## Example of how the command registration process might work:

An external client sends a POST request to the Command API to register a command.
The Command API validates the command and writes it to the local file-based command database.
The Dispatcher API, which subscribes to the Event API, detects the new command based on relevant events.
It schedules the command for execution by adding it to the task queue.
Task workers periodically poll the Dispatcher API for new commands.
When a worker receives a command, it executes the steps and generates events.
The worker writes these events to the Event API, which stores them in the local file-based event log.
The Dispatcher API, subscribed to the Event API, detects the new events.
It may then schedule more commands based on these events, continuing the workflow.
For the local file-based databases, you can use structured directories and files, or consider using lightweight databases like SQLite to manage the data efficiently. Each database (commands and events) could be organized with subdirectories for each workflow, ensuring isolation and ease of retrieval.
