#!/usr/bin/env python3
"""
Script to create a Google Cloud service account for NoETL.

This script creates a service account with the name 'noetl-service-account'
in the project 'noetl-demo-19700101', grants it the necessary permissions,
and generates a key file.

Usage:
    python create_service_account.py [--email YOUR_EMAIL]

Options:
    --email Google account email for impersonation permissions
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def run_command(command, check=True):
    print(f"Running: {command}")
    result = subprocess.run(command, shell=True, check=check, 
                           capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result

def create_service_account():
    parser = argparse.ArgumentParser(description='Create a Google Cloud service account for NoETL')
    parser.add_argument('--email', help='Your Google account email for impersonation permissions')
    args = parser.parse_args()
    project_id = "noetl-demo-19700101"
    sa_name = "noetl-service-account"
    sa_email = f"{sa_name}@{project_id}.iam.gserviceaccount.com"
    secrets_dir = Path(".secrets")
    key_file = secrets_dir / f"{sa_name}.json"
    print(f"\n=== Step 1: Setting active project to {project_id} ===")
    run_command(f"gcloud config set project {project_id}")
    run_command("gcloud config get-value project")
    print(f"\n=== Step 2: Creating service account {sa_name} ===")
    create_sa_cmd = (
        f"gcloud iam service-accounts create {sa_name} "
        f"--project={project_id} "
        f"--display-name=\"NoETL Service Account\""
    )
    run_command(create_sa_cmd, check=False)
    print(f"\n=== Step 3: Granting Storage Admin role ===")
    grant_role_cmd = (
        f"gcloud projects add-iam-policy-binding {project_id} "
        f"--member=\"serviceAccount:{sa_email}\" "
        f"--role=\"roles/storage.admin\""
    )
    run_command(grant_role_cmd)

    print(f"\n=== Step 3.1: Granting Secret Manager Secret Accessor role ===")
    grant_secret_role_cmd = (
        f"gcloud projects add-iam-policy-binding {project_id} "
        f"--member=\"serviceAccount:{sa_email}\" "
        f"--role=\"roles/secretmanager.secretAccessor\""
    )
    run_command(grant_secret_role_cmd)
    if args.email:
        print(f"\n=== Step 4: Granting impersonation permission to {args.email} ===")
        impersonate_cmd = (
            f"gcloud iam service-accounts add-iam-policy-binding {sa_email} "
            f"--member=\"user:{args.email}\" "
            f"--role=\"roles/iam.serviceAccountTokenCreator\""
        )
        run_command(impersonate_cmd)
    else:
        print("\n=== Step 4: Skipping impersonation permission (no email provided) ===")

    print(f"\n=== Step 5: Creating service account key ===")
    secrets_dir.mkdir(exist_ok=True)
    key_cmd = (
        f"gcloud iam service-accounts keys create {key_file} "
        f"--iam-account={sa_email}"
    )
    run_command(key_cmd)
    print(f"\n=== Step 6: Creating HMAC keys ===")
    hmac_cmd = (
        f"gcloud alpha storage hmac-keys create {sa_email} "
        f"--project={project_id} --format=json"
    )
    result = run_command(hmac_cmd)

    try:
        hmac_output = json.loads(result.stdout)
        access_key = hmac_output.get('accessId')
        secret_key = hmac_output.get('secret')

        print("\nHMAC Keys created successfully:")
        print(f"Access Key ID: {access_key}")
        print(f"Secret Key: {secret_key}")
        hmac_file = secrets_dir / f"{sa_name}_hmac_keys.json"
        with open(hmac_file, 'w') as f:
            json.dump({
                'access_key_id': access_key,
                'secret_access_key': secret_key
            }, f, indent=2)
        print(f"HMAC keys saved to {hmac_file}")
    except json.JSONDecodeError:
        print("Could not parse HMAC keys output. Please check the command output.")
    print(f"\n=== Step 7: Verifying service account ===")
    run_command(f"gcloud iam service-accounts describe {sa_email}")
    print("\n=== Setup Complete ===")
    print(f"Service account: {sa_email}")
    print(f"Key file: {key_file}")
    print("\nTo use this service account with NoETL, add the following to your .env.examples file:")
    print(f"GOOGLE_CLOUD_PROJECT=\"{project_id}\"")
    print(f"GOOGLE_APPLICATION_CREDENTIALS=\"{os.path.abspath(key_file)}\"")
    print(f"SERVICE_ACCOUNT_EMAIL=\"{sa_email}\"")

    print("\nThen run the playbook:")
    print("source bin/load_env_files.sh dev")
    print("noetl agent -f playbook/generate_gcs_hmac_keys.yaml")

if __name__ == "__main__":
    create_service_account()
