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