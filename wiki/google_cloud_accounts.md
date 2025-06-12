# Switching Between Google Service Account and Regular User Account

This guide explains how to switch between your **regular Google Cloud user account** and a **service account** for running scripts, managing resources, and general GCP operations.
---

## 1. Understanding Accounts

- **Regular Account:** Your personal or work Google account (e.g., `user@gmail.com`). Used for interactive work, billing, and initial setup.
- **Service Account:** A non-human account for automation, scripts, CI/CD, and secure service-to-service operations.

---

## 2. Authenticating with gcloud

### A. Authenticate as a Regular User
```bash
gcloud auth login
```

- Opens a browser for OAuth authentication.
- Sets your user credentials for `gcloud` and `gsutil` commands.

### B. Authenticate as a Service Account
```bash
gcloud auth activate-service-account –key-file=.secrets/noetl-demo.json
```
- Uses the downloaded service account key.
- Sets the active account for `gcloud` and `gsutil`.

---

## 3. Application Default Credentials (ADC)

Some tools (Python SDKs, Docker containers, etc.) use ADC, which is set separately from `gcloud auth login`.

### A. Set ADC to Service Account
```bash
export GOOGLE_APPLICATION_CREDENTIALS=”$(pwd)/.secrets/noetl-demo.json”
```
- Most SDKs and tools will now use this service account for authentication.

### B. Set ADC to User Account
```bash
gcloud auth application-default login
```
- Sets up ADC for your user account.

---

## 4. Switching Projects

Set the active project for all `gcloud` commands:
```bash
gcloud config set project <PROJECT_ID>
```
Check the current project:
```bash
gcloud config get-value project
```

List all accessible projects:
```bash
gcloud projects list
```

---

## 5. Service Account Permissions

To allow a user to impersonate a service account (e.g., for `gcloud auth impersonate-service-account`):
```bash
gcloud iam service-accounts add-iam-policy-binding noetl-demo@<PROJECT_ID>.iam.gserviceaccount.com 
–member="user:<user@gmail.com>" 
–role="roles/iam.serviceAccountTokenCreator"
```
---

## 6. Creating and Managing Service Account Keys

Create a service account key and store it securely:
```bash
gcloud iam service-accounts keys create .secrets/noetl-demo.json 
–iam-account=noetl-demo@<PROJECT_ID>.iam.gserviceaccount.com
```
---

## 7. Switching Contexts in Practice

### To use regular account for CLI work
```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
```

### To use a service account for automation/scripts
```bash
gcloud auth activate-service-account –key-file=.secrets/noetl-demo.json
gcloud config set project <PROJECT_ID>
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/.secrets/noetl-demo.json"
```

### To switch ADC back to user
```bash
gcloud auth application-default login
```
---

## 8. Best Practices

- **Never commit service account keys to source control.** Store them in secure locations or use secret managers.
- **Use service accounts for automation and production workloads.**
- **Use user accounts for interactive and ad-hoc work.**
- **Set the correct project before running scripts to avoid accidental resource creation in the wrong project.**

---

## Summary

| Task                      | Command/Action                                                      |
|---------------------------|---------------------------------------------------------------------|
| Login as user             | `gcloud auth login`                                                 |
| Activate service account  | `gcloud auth activate-service-account --key-file=KEY.json`          |
| Set ADC to service acct   | `export GOOGLE_APPLICATION_CREDENTIALS=PATH/KEY.json`               |
| Set ADC to user           | `gcloud auth application-default login`                             |
| Set active project        | `gcloud config set project PROJECT_ID`                              |
| Check current project     | `gcloud config get-value project`                                   |
| List projects             | `gcloud projects list`                                              |
| Add impersonation rights  | `gcloud iam service-accounts add-iam-policy-binding ...`            |
| Create SA key             | `gcloud iam service-accounts keys create ...`                       |

---

**For secure, automated workflows, use service accounts for scripts and automation, and switch back to your user account for interactive work.**  
**Store sensitive keys securely and clean up unused keys and permissions.**