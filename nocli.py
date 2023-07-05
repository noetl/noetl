import aiohttp
import asyncio
import aioconsole
import yaml
import argparse

# Define the GraphQL queries and mutations
queries = {
    "getWorkflows": """
        query {
            getWorkflows {
                name
                status
            }
        }
    """
}

mutations = {
    "submitWorkflow": """
        mutation ($workflowInput: WorkflowInput!) {
            submitWorkflow(input: $workflowInput) {
                name
                status
            }
        }
    """
}

# Define the base URL of the FastAPI server
base_url = "http://localhost:8000/graphql"


# Function to make an asynchronous GraphQL request
async def make_request(query, variables=None):
    async with aiohttp.ClientSession() as session:
        payload = {
            "query": query,
            "variables": variables
        }
        async with session.post(base_url, json=payload) as response:
            return await response.json()


# Function to submit a workflow
async def submit_workflow(workflow_input):
    mutation = mutations["submitWorkflow"]
    variables = {
        "workflowInput": workflow_input
    }
    response = await make_request(mutation, variables)
    return response["data"]["submitWorkflow"]


# Function to retrieve workflows
async def get_workflows():
    query = queries["getWorkflows"]
    response = await make_request(query)
    return response["data"]["getWorkflows"]


# Convert YAML to workflow input
def convert_yaml_to_workflow_input(yaml_content):
    # Implement the conversion logic based on your YAML structure
    workflow_input = {
        "name": yaml_content["metadata"]["name"],
        "spec": yaml_content["spec"]
    }
    return yaml_content


# Submit workflow command
async def submit_workflow_command():
    # Read YAML configuration from file
    with open("example_workflow.yaml") as file:
        yaml_content = yaml.safe_load(file)

    # Convert YAML to workflow input
    workflow_input = convert_yaml_to_workflow_input(yaml_content)

    # Submit the workflow asynchronously
    submitted_workflow = await submit_workflow(workflow_input)

    print(f"Submitted Workflow: Name: {submitted_workflow['name']}, Status: {submitted_workflow['status']}")


# Get workflows command
async def get_workflows_command():
    workflows = await get_workflows()

    print("Workflows:")
    for workflow in workflows:
        print(f"Name: {workflow['name']}, Status: {workflow['status']}")


def parse_arguments():
    """
    Parses command-line arguments.
    :return: An argparse.Namespace object containing the parsed command-line arguments.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(prog="NoETL", description="Not Only ETL is a Workflow Engine that utilizes \
                            a loop-based approach to dispatch the execution of workflows.")
    parser.add_argument("-c", "--config")
    return parser.parse_args()


# Main loop

async def main():
    while True:
        command = await aioconsole.ainput("Enter a command (submit/get/exit): ")

        if command == "submit":
            config_path = await aioconsole.ainput("Enter the path to the workflow config YAML file: ")
            try:
                with open(config_path) as file:
                    yaml_content = yaml.safe_load(file)
                    workflow_input = convert_yaml_to_workflow_input(yaml_content)
                    submitted_workflow = await submit_workflow(workflow_input)
                    print(
                        f"Submitted Workflow: Name: {submitted_workflow['name']}, Status: {submitted_workflow['status']}")
            except FileNotFoundError:
                print("File not found. Please enter a valid path.")
            except yaml.YAMLError:
                print("Invalid YAML file. Please check the syntax.")
        elif command == "get":
            await get_workflows_command()
        elif command == "exit":
            break
        else:
            print("Invalid command. Please try again.")


# Run the main loop
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
