# Creating a Google Cloud Service Account for NoETL

This guide explains how to create a Google Cloud service account specifically for use with NoETL. 

The instructions create a service account with the name `noetl-service-account` in the project `noetl-demo-19700101`.

## Prerequisites

1. Google Cloud SDK (gcloud) installed on your machine
2. Permissions to create service accounts in the Google Cloud project
3. The project `noetl-demo-19700101` already created in Google Cloud

## Step 1: Set the Active Project

List all authenticated accounts
```shell
gcloud auth list
```

Authenticate with google account
```shell
gcloud auth login kadyapam@gmail.com --force
```

Set the active account 
```shell
gcloud config set account kadyapam@gmail.com
```

set your active Google Cloud project:

```bash
gcloud config set project noetl-demo-19700101
```

Verify that the project is set correctly:

```bash
gcloud config get-value project
```

Update application default credentials
```shell
gcloud auth application-default login
```

Verify the active account
```shell
gcloud config get-value account
```

## Step 2: Create the Service Account

Create the service account with the specified name:

```bash
gcloud iam service-accounts create noetl-service-account \
  --project=noetl-demo-19700101 \
  --display-name="NoETL Service Account"
```

This creates a service account with the email address: `noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com`

## Step 3: Grant Permissions

Grant the service account the Storage Admin role to allow it to manage Google Cloud Storage resources:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/storage.admin"
```

Grant the service account the Secret Manager Secret Accessor role to allow it to read secrets from Secret Manager:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

If you need to grant additional roles, you can add more `add-iam-policy-binding` commands with different roles.

For a comprehensive guide on granting all the necessary permissions for NoETL operations, see [Granting Required Permissions to Service Accounts](grant_service_account_permissions.md).

## Step 4: Grant User Permission to Impersonate the Service Account

To impersonate the service account from your user account, run:

```bash
gcloud iam service-accounts add-iam-policy-binding noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com \
  --member="user:kadyapam@gmail.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

## Step 5: Create a Service Account Key

Create a key file for the service account:

```bash
mkdir -p .secrets
gcloud iam service-accounts keys create .secrets/noetl-service-account.json \
  --iam-account=noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com
```

**Important**: Keep this key file secure and never commit it to source control.

## Step 6: Create HMAC Keys for Google Cloud Storage

Create HMAC keys for S3-compatible access to Google Cloud Storage:

```bash
gcloud storage hmac create noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com \
  --project=noetl-demo-19700101
```

This will output an Access Key ID and Secret that you can use for S3-compatible access.

## Step 7: Using the Service Account with NoETL

### Option 1: Set Environment Variables

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/.secrets/noetl-service-account.json"
export GOOGLE_CLOUD_PROJECT="noetl-demo-19700101"
```

### Option 2: Use with the GCS HMAC Keys Generator Playbook

Update your `.env.examples` file with:

```bash
GOOGLE_CLOUD_PROJECT="noetl-demo-19700101"
GOOGLE_APPLICATION_CREDENTIALS=".secrets/noetl-service-account.json"
SERVICE_ACCOUNT_EMAIL="noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com"
```

Then run the playbook:

```bash
set -a; source .env.example; noetl agent -f playbook/generate_gcs_hmac_keys.yaml
```

## Verification

To verify that the service account was created successfully:

```bash
gcloud iam service-accounts describe noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com
```

To list all service accounts in the project:

```bash
gcloud iam service-accounts list --project=noetl-demo-19700101
```

To check if the service account key file is valid and contains the expected type:
```bash
```shell
cat $GOOGLE_APPLICATION_CREDENTIALS | jq -r '.type == "service_account"'
```

## Best Practices

1. **Security**: Never commit service account keys to source control
2. **Least Privilege**: Grant only the permissions that are absolutely necessary
3. **Key Rotation**: Regularly rotate service account keys
4. **Monitoring**: Set up monitoring and auditing for service account usage
