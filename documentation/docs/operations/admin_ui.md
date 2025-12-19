# NoETL UI

NoETL UI for creating, editing, and executing NoETL playbooks.

## Overview

The NoETL Playbook Editor UI provides a visual interface for working with NoETL playbooks: 

1. **Catalog View**: View, manage, and execute playbooks from the catalog
2. **Block-Based Editor**: Create and edit playbooks using a visual, block-based interface
3. **Execution View**: Monitor the execution of playbooks in real-time

## Installation

The UI is integrated with the NoETL server and requires no additional installation. 

```bash
noetl server
```

By default, the UI is accessible at `http://localhost:8082`.

## Features

### Catalog View

The catalog view provides a list of all playbooks in the NoETL catalog:

- View all playbooks in the catalog
- Create new playbooks
- Edit existing playbooks
- Execute playbooks
- View playbook details

### Block-Based Editor

The block-based editor allows you to create and edit playbooks using a visual interface:

- A canvas for arranging and connecting workflow steps
- A properties panel for editing step properties
- Tabs for editing the workflow, workload, and YAML representation of the playbook
- Buttons for saving, executing, exporting, and importing playbooks

#### Creating a New Playbook

To create a new playbook:

1. Click the "Create New Playbook" button in the catalog view
2. Use the block-based editor to add steps, tasks, and conditions to the workflow
3. Edit the properties of each step in the properties panel
4. Save the playbook to the catalog

#### Editing an Existing Playbook

To edit an existing playbook:

1. Click the "Edit" button for the playbook in the catalog view
2. Use the block-based editor to modify the workflow
3. Save the changes to the catalog

### Execution View

The execution view allows you to monitor the execution of playbooks in real-time. The view provides:

- The current status of the execution
- Details about the execution (ID, playbook, version, start time, end time, duration)
- A list of execution steps and their status
- The results of the execution

## Usage Examples

### Example 1: Creating a Simple Playbook

1. Click the "Create New Playbook" button in the catalog view
2. Add a "Start" step to the workflow
3. Add a "Fetch Data" task to the workflow
4. Connect the "Start" step to the "Fetch Data" task
5. Edit the properties of the "Fetch Data" task to specify the data source
6. Save the playbook to the catalog

### Example 2: Executing a Playbook

1. Find the playbook in the catalog view
2. Click the "Execute" button for the playbook
3. View the execution status in the execution view
4. When the execution is complete, view the results

## Technical Details

The UI is built using the following technologies:

- **Frontend**: HTML, CSS, JavaScript, React
- **UI Framework**: Ant Design
- **Block-Based Editor**: React Flow
- **Code Editor**: Monaco Editor
- **Backend**: FastAPI

The UI is served by the NoETL server and communicates with the server using REST API calls.

## Troubleshooting

If you encounter issues with the UI:

1. Check the browser console for error messages
2. Check the NoETL server logs for error messages
3. Report the issue on the NoETL GitHub repository

## Future Enhancements

Planned enhancements for the UI include:

1. **Improved Block-Based Editor**: More node types, better connection handling, and improved layout
2. **Collaborative Editing**: Allow multiple users to edit the same playbook simultaneously
3. **Version History**: View and restore previous versions of playbooks
4. **Execution History**: View the history of playbook executions
5. **Debugging Tools**: Step through playbook execution for debugging
