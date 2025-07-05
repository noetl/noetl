# Google Cloud Service Account Guide for NoETL

This comprehensive guide covers everything you need to know about working with Google Cloud service accounts for NoETL, including:

1. Creating a service account
2. Granting necessary permissions
3. Entering service account impersonation
4. Exiting service account impersonation
5. Best practices

## Creating a Google Cloud Service Account

This section explains how to create a Google Cloud service account specifically for use with NoETL.

The instructions create a service account with the name `noetl-service-account` in the project `noetl-demo-19700101`.

### Prerequisites

1. Google Cloud SDK (gcloud) installed on the machine
2. Permissions to create service accounts in the Google Cloud project
3. The project `noetl-demo-19700101` already created in Google Cloud

### Step 1: Set the Active Project

List all authenticated accounts
```shell
gcloud auth list
```

Authenticate with google account
```shell
gcloud auth login user@gmail.com --force
```

Set the active account 
```shell
gcloud config set account user@gmail.com
```

Set active Google Cloud project:

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

### Step 2: Create the Service Account

Create the service account with the specified name:

```bash
gcloud iam service-accounts create noetl-service-account \
  --project=noetl-demo-19700101 \
  --display-name="NoETL Service Account"
```

This creates a service account with the email address: `noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com`

### Step 3: Grant User Permission to Impersonate the Service Account

To impersonate the service account from the user account, run:

```bash
gcloud iam service-accounts add-iam-policy-binding noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com \
  --member="user:kadyapam@gmail.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

### Step 4: Create a Service Account Key

Create a key file for the service account:

```bash
mkdir -p .secrets
gcloud iam service-accounts keys create .secrets/noetl-service-account.json \
  --iam-account=noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com
```

**Important**: Keep this key file secure and never commit it to source control.

### Step 5: Create HMAC Keys for Google Cloud Storage

Create HMAC keys for S3-compatible access to Google Cloud Storage:

```bash
gcloud storage hmac create noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com \
  --project=noetl-demo-19700101
```

This will output an Access Key ID and Secret that will be used for S3-compatible access.

### Step 6: Using the Service Account with NoETL

#### Option 1: Set Environment Variables

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/.secrets/noetl-service-account.json"
export GOOGLE_CLOUD_PROJECT="noetl-demo-19700101"
```

### Verification

To verify that the service account was created successfully:

```bash
gcloud iam service-accounts describe noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com
```

To list all service accounts in the project:

```bash
gcloud iam service-accounts list --project=noetl-demo-19700101
```

To check if the service account key file is valid and contains the expected type:
```shell
cat $GOOGLE_APPLICATION_CREDENTIALS | jq -r '.type == "service_account"'
```

## Granting Required Permissions to Service Accounts

This section explains how to grant the necessary permissions to a service account for use with NoETL, focusing on Google Cloud Storage and Secret Manager access.

### Required Permissions

Based on common error messages, the service account needs the following permissions:

1. **For Google Cloud Storage access**:
   - `storage.objects.list` - To list objects in a bucket
   - `storage.buckets.get` - To access bucket metadata

2. **For Secret Manager access**:
   - `secretmanager.secrets.list` - To list secrets in a project
   - `secretmanager.secrets.get` - To get secret metadata
   - `secretmanager.versions.access` - To access secret versions

### Granting the Required Roles

The easiest way to grant these permissions is by assigning predefined IAM roles that include these permissions.

#### For Google Cloud Storage

To grant full access to Google Cloud Storage:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/storage.admin"
```

For read-only access to objects:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

#### For Secret Manager

To grant permission to list and access secrets:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

To grant full access to Secret Manager:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/secretmanager.admin"
```

### Example for NoETL Service Account

For the NoETL service account, run:

```bash
gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding noetl-demo-19700101 \
  --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
  --role="roles/secretmanager.admin"
```

### Verifying Permissions

After granting the roles, verify the permissions:

```bash
gcloud projects get-iam-policy noetl-demo-19700101 \
  --flatten="bindings[].members" \
  --format="table(bindings.role,bindings.members)" \
  --filter="bindings.role:storage"

gcloud projects get-iam-policy noetl-demo-19700101 \
  --flatten="bindings[].members" \
  --format="table(bindings.role,bindings.members)" \
  --filter="bindings.role:secretmanager"
```

## Entering Service Account Impersonation

This section explains how to enter Google Cloud service account impersonation mode, allowing it to act as a service account without needing its key file.

### Why Use Service Account Impersonation?

Service account impersonation allows:

1. **Temporarily assume a service account's identity** without managing key files
2. **Test permissions and access** before deploying applications
3. **Perform administrative tasks** that require service account permissions
4. **Follow the principle of least privilege** by using temporary credentials

### Prerequisites

Before you can impersonate a service account, ensure:

1. Google Cloud user account exists with sufficient permissions
2. The service account exists in Google Cloud project
3. User account has been granted the `roles/iam.serviceAccountTokenCreator` role for the service account
4. The service account has all the necessary permissions for the operations are intended to perform

### Methods for Entering Impersonation Mode

There are two main methods to enter service account impersonation mode:

#### Method 1: Using Service Account Impersonation (Recommended)

This method allows you to impersonate a service account without needing its key file:

```bash
gcloud auth print-access-token --impersonate-service-account=SERVICE_ACCOUNT_EMAIL
```

For a more persistent impersonation session:

```bash
gcloud config set auth/impersonate_service_account SERVICE_ACCOUNT_EMAIL
```

To verify the impersonation is active:

```bash
gcloud config get-value account
```

This should show the service account email.

#### Method 2: Using a Service Account Key File

This method requires a service account key file:

```bash
gcloud auth activate-service-account --key-file=PATH_TO_KEY_FILE
```

For example:

```bash
gcloud auth activate-service-account --key-file=.secrets/noetl-service-account.json
```

### Setting Application Default Credentials (ADC)

For applications that use Application Default Credentials:

#### With Impersonation

```bash
export GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=SERVICE_ACCOUNT_EMAIL
```

#### With Key File

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/PATH_TO_KEY_FILE"
```

### Example: Testing Service Account Permissions

Here's an example of how to impersonate a service account to test its permissions:

1. Enter impersonation mode:
   ```bash
   gcloud config set auth/impersonate_service_account noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com
   ```

2. Test access to a Google Cloud Storage bucket:
   ```bash
   gsutil ls gs://noetl-samples/
   ```

3. Test access to Secret Manager:
   ```bash
   gcloud secrets list --project=noetl-demo-19700101
   ```

## Exiting Service Account Impersonation

This section explains how to exit from Google Cloud service account impersonation and return to your regular user account. 

### Why Exit from Impersonation?

When you're impersonating a service account, you're acting as that service account. However, some operations, such as granting permissions to a service account, require to be authenticated as a user with sufficient permissions, and not the service account itself. In these cases, exit from impersonation and return to your regular user account.

If you encounter permission errors while using an impersonated service account, such as "Permission denied" for Google Cloud Storage or Secret Manager operations, exit impersonation, grant the necessary permissions to the service account, and then re-enter impersonation.

### Steps to Exit from Service Account Impersonation

#### 1. Check Your Current Active Account

First, check which account is currently in use:

```bash
gcloud config get-value account
```

If this shows a service account email (ending with `.iam.gserviceaccount.com`), it is an impersonated service account.

#### 2. Exit from Impersonation and Return to User Account

To exit from impersonation and return to regular user account, run:

```bash
gcloud auth login
```

This will open a browser window to authenticate with regular Google account.

#### 3. Verify the Switch

After logging in, verify that a regular user account is in use:

```bash
gcloud config get-value account
```

This should now show the regular user email address.

#### 4. For Application Default Credentials (ADC)

If the Application Default Credentials (ADC) are in use in your application, it is required to reset those:

```bash
gcloud auth application-default login
```

This will set up ADC for the user account.

### Example: Granting Permissions to a Service Account

Here's an example of how to exit from impersonation to grant permissions to a service account:

1. Exit from impersonation:
   ```bash
   gcloud auth login
   ```

2. Grant permissions to the service account:
   ```bash
   gcloud projects add-iam-policy-binding noetl-demo-19700101 \
     --member="serviceAccount:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```

3. Verify the permissions were granted:
   ```bash
   gcloud projects get-iam-policy noetl-demo-19700101 \
     --flatten="bindings[].members" \
     --format="table(bindings.role,bindings.members)" \
     --filter="bindings.members:noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com"
   ```

## Important Note About Impersonation

When using service account impersonation, you need to ensure:

1. User account has the `roles/iam.serviceAccountTokenCreator` role for the service account
2. The service account itself has the necessary permissions for the operations

If you're still encountering permission issues after granting the roles, you may need to exit impersonation mode, grant the permissions, and then re-enter impersonation mode:

```bash
gcloud config unset auth/impersonate_service_account

gcloud config set auth/impersonate_service_account noetl-service-account@noetl-demo-19700101.iam.gserviceaccount.com
```

## Best Practices

### Security Best Practices

1. **Never commit service account keys to source control**
2. **Use impersonation over key files** when possible for better security
3. **Limit the duration** of your impersonation sessions
4. **Verify which account you're using** before performing sensitive operations
5. **Never share impersonation credentials** with unauthorized users

### Permission Best Practices

1. **Least Privilege**: Grant only the permissions that are only necessary
2. **Ensure the service account has the necessary permissions** before attempting to use it
3. **Return to your regular user account** for administrative tasks like granting permissions

### Operational Best Practices

1. **Key Rotation**: Regularly rotate service account keys
2. **Monitoring**: Set up monitoring and auditing for service account usage
3. **Keep your authentication contexts separate** to avoid confusion and potential security issues
4. **Always be aware of which account you're currently using**, especially when performing sensitive operations
5. **Use service accounts only for the specific tasks** they're designed for