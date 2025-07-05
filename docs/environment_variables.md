# NoETL Environment Configuration Guide

1. Overview of environment configuration
2. Setting up environment files
3. Loading environment variables
4. Using environment variables in playbooks
5. Best practices

## Overview of Environment Configuration

NoETL uses the Multiple Environment Files approach for managing environment-specific configuration:

**Multiple Environment Files**: Using separate files for different environments `.env.dev`, `.env.prod`, etc.

This approach is the recommended standard for NoETL projects.

## Multiple Environment Files Approach

**Pros:**
- Industry standard approach
- Better security isolation between environments
- Can selectively gitignore production environment files
- Supported by many tools out of the box

**Considerations:**
- Duplication of common variables across files
- More files to manage
- Harder to see differences between environments
- Changes to common variables must be made in multiple files

## Setting Up Environment Files

Create separate files for different environments:

- `.env.common` - Common variables for all environments
- `.env.dev` - Development environment variables
- `.env.prod` - Production environment variables
- `.env.local` - Local overrides, not committed to version control
- `.env.example` - Example environment file with documentation

## Example Environment Files

### `.env.common`
```
# Common variables for all environments
PRJDIR="$(pwd)"
PYTHONPATH=${PRJDIR}/noetl:${PRJDIR}/tests:${PYTHONPATH}

# Google Secret Manager Configuration
# Path to Google application credentials file for local development
GOOGLE_APPLICATION_CREDENTIALS=${PRJDIR}/secrets/application_default_credentials.json
```

### `.env.dev`
```
# Development environment variables
ENVIRONMENT="dev"

# Google Secret Manager references
# Format: projects/PROJECT_ID/secrets/SECRET_NAME
GOOGLE_SECRET_POSTGRES_PASSWORD="projects/123456789/secrets/postgres-dev-password"
GOOGLE_SECRET_API_KEY="projects/123456789/secrets/api-dev-key"

# LastPass Configuration
LASTPASS_USERNAME="dev-user@example.com"
LASTPASS_PASSWORD="your-dev-password"
```

### `.env.prod`
```
# Production environment variables
ENVIRONMENT="prod"

# Google Secret Manager references
# Format: projects/PROJECT_ID/secrets/SECRET_NAME
GOOGLE_SECRET_POSTGRES_PASSWORD="projects/123456789/secrets/postgres-prod-password"
GOOGLE_SECRET_API_KEY="projects/123456789/secrets/api-prod-key"

# LastPass Configuration
LASTPASS_USERNAME="prod-user@example.com"
LASTPASS_PASSWORD="your-prod-password"
```

## Loading Environment Variables

To load variables from separate environment files:

```bash
# Load development environment - default setting
source bin/load_env.sh

# Specify an environment explicitly
source bin/load_env.sh dev
source bin/load_env.sh prod
```

### Testing Environment Variables

To test that variables are loaded correctly:

```bash
./bin/test_env.sh
./bin/test_env.sh dev
./bin/test_env.sh prod
```

### Scripts

There are two scripts that load environment variables and run NoETL commands:

#### Starting the Server

```bash
./bin/start_server.sh [dev|prod|test]
```

This script loads the environment variables and starts the NoETL server.

#### Running the Agent

```bash
./bin/run_agent.sh [dev|prod|test] -f playbook_file.yaml [other_options]
```

This script loads the environment variables and runs the NoETL agent with the specified playbook file.

### Manual Loading

Manually load environment variables using the `set -a` command:

```bash
set -a
source .env.dev
set +a
noetl server
```

Or in one line:

```bash
set -a; source .env.dev; noetl server
```

## Using Environment Variables in Playbooks

In NoETL playbooks, you can access environment variables using the `env` object:

```yaml
workload:
  # Access a common variable
  project_dir: "{{ env.PRJDIR }}"

  # Access an environment specific variable
  postgres_password: "{{ env.GOOGLE_SECRET_POSTGRES_PASSWORD }}"
  api_key: "{{ env.GOOGLE_SECRET_API_KEY }}"
  lastpass_username: "{{ env.LASTPASS_USERNAME }}"
```

### Conditional Logic Based on Environment

To use conditional logic in NoETL playbooks to handle different environments:

```yaml
workload:
  # Use different values based on the current environment
  environment: "{{ env.ENVIRONMENT }}"
  is_dev: "{{ env.ENVIRONMENT == 'dev' }}"
  is_prod: "{{ env.ENVIRONMENT == 'prod' }}"

  # Example of conditional logic
  database_host: "{{ 'localhost' if env.ENVIRONMENT == 'dev' else 'production-db.example.com' }}"
```

## Setting Up for a New Project

1. Copy `.env.example` to create your environment files:
   ```bash
   cp .env.example .env.common
   cp .env.example .env.dev
   cp .env.example .env.prod
   cp .env.example .env.local
   ```

2. Edit each file to include only the relevant variables:
   - `.env.common`: Common variables for all environments
   - `.env.dev`: Development specific variables
   - `.env.prod`: Production specific variables
   - `.env.local`: Local overrides

3. Update your `.gitignore` to exclude sensitive files:
   ```
   .env.prod
   .env.local
   ```

4. Load the environment variables:
   ```bash
   source bin/load_env.sh dev
   ```

## Common Issues

### Authentication Errors

If you encounter authentication errors when accessing Google Cloud services, make sure:

1. The correct environment variables are loaded
2. The `GOOGLE_APPLICATION_CREDENTIALS` environment variable points to a valid credentials file
3. The service account has the necessary permissions for the operation

### Missing Environment Variables

If environment variables are missing, check:

1. The environment file for the current environment (e.g., `.env.dev`)
2. The `.env.common` file for common variables
3. The `.env.local` file for local overrides

## Best Practices

1. **Common Variables**: Place variables that are the same across all environments in the `.env.common` file.
2. **Environment-Specific Variables**: Place variables that differ between environments in the environment specific file (`.env.dev`, `.env.prod`, etc.).
3. **Sensitive Information**: Never commit sensitive information, like passwords, API keys, to version control. Use placeholder values in the `.env.example` file and document how to set the real values.
4. **Documentation**: Document all environment variables used by your application, including their purpose and expected values.
5. **Default Values**: Provide sensible default values for optional environment variables.
6. **Use Descriptive Variable Names**: Use names that indicate the purpose of the variable.
7. **Least Privilege**: Grant only the permissions that are only necessary.
8. **Local Overrides**: Use `.env.local` for local development overrides that shouldn't be committed to version control.
