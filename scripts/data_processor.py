#!/usr/bin/env python3
"""
Simple data processor script for testing K8s job execution.

This script demonstrates:
- Receiving arguments as JSON
- Accessing environment variables (including OAuth2 credentials from keychain)
- Processing data with configurable mode
- Writing results to GCS using google-cloud-storage library
- Outputting structured results
"""

import sys
import json
import os
import urllib.request
import urllib.error
from datetime import datetime

def main():
    # Parse arguments from command line (passed as JSON string)
    if len(sys.argv) > 1:
        args = json.loads(sys.argv[1])
    else:
        args = {}
    
    input_file = args.get('input_file', 'unknown')
    output_bucket = args.get('output_bucket', 'unknown')
    mode = args.get('mode', 'default')
    
    # Access GCP service account JSON from environment
    gcp_sa_json = os.environ.get('GCP_SERVICE_ACCOUNT_JSON', 'not_set')
    gcs_bucket = os.environ.get('GCS_BUCKET', 'not_set')
    gcp_project = os.environ.get('GCP_PROJECT', 'not_set')
    
    sa_available = gcp_sa_json != 'not_set'
    
    print(f"[DATA PROCESSOR] Starting in {mode} mode")
    print(f"[DATA PROCESSOR] Input: {input_file}")
    print(f"[DATA PROCESSOR] Output bucket: {output_bucket}")
    print(f"[DATA PROCESSOR] Service account available: {sa_available}")
    if sa_available:
        print(f"[DATA PROCESSOR] SA JSON type: {type(gcp_sa_json)}")
        print(f"[DATA PROCESSOR] SA JSON first 150 chars: {repr(gcp_sa_json[:150])}")
    print(f"[DATA PROCESSOR] GCS Bucket from env: {gcs_bucket}")
    print(f"[DATA PROCESSOR] GCP Project from env: {gcp_project}")
    
    # Simulate processing
    records_processed = 1000
    print(f"[DATA PROCESSOR] Processed {records_processed} records")
    
    # Write results to GCS if service account is available
    output_location = f"gs://{output_bucket}/results/output.csv"
    wrote_to_gcs = False
    
    if sa_available:
        try:
            print(f"[DATA PROCESSOR] Attempting to write to GCS: {output_location}")
            
            # Generate CSV content
            csv_content = "id,name,value,timestamp\n"
            for i in range(1, min(records_processed + 1, 11)):  # First 10 rows as sample
                csv_content += f"{i},record_{i},{i * 100},{datetime.utcnow().isoformat()}\n"
            
            # Parse service account JSON
            print(f"[DATA PROCESSOR] Attempting to parse SA JSON...")
            print(f"[DATA PROCESSOR] Raw value length: {len(gcp_sa_json)}")
            
            # Try to detect if it's already a dict (shouldn't happen with env var, but check)
            if isinstance(gcp_sa_json, dict):
                print(f"[DATA PROCESSOR] SA is already a dict, using directly")
                sa_info = gcp_sa_json
            else:
                # It's a string, try to parse
                print(f"[DATA PROCESSOR] SA is string, parsing with json.loads()")
                sa_info = json.loads(gcp_sa_json)
            
            # Generate access token from service account
            from google.oauth2 import service_account
            import google.auth.transport.requests
            
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=['https://www.googleapis.com/auth/devstorage.read_write']
            )
            
            # Refresh to get access token
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
            access_token = credentials.token
            
            print(f"[DATA PROCESSOR] Generated access token from service account")
            
            # Upload to GCS using REST API with generated token
            gcs_url = f"https://storage.googleapis.com/upload/storage/v1/b/{output_bucket}/o?uploadType=media&name=results/output.csv"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "text/csv"
            }
            
            request_obj = urllib.request.Request(
                gcs_url,
                data=csv_content.encode('utf-8'),
                headers=headers,
                method='POST'
            )
            
            print(f"[DATA PROCESSOR] Uploading {len(csv_content)} bytes...")
            with urllib.request.urlopen(request_obj) as response:
                if response.status in (200, 201):
                    wrote_to_gcs = True
                    print(f"[DATA PROCESSOR] ✓ Successfully wrote to {output_location}")
                else:
                    print(f"[DATA PROCESSOR] ✗ Failed to write to GCS: HTTP {response.status}")
            
        except urllib.error.HTTPError as e:
            print(f"[DATA PROCESSOR] ✗ HTTP Error: {e.code} - {e.read().decode('utf-8')}")
        except Exception as e:
            print(f"[DATA PROCESSOR] ✗ Failed to write to GCS: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"[DATA PROCESSOR] ⚠ Service account not available, skipping GCS upload")
    
    # Output result as JSON
    result = {
        "status": "completed",
        "records_processed": records_processed,
        "input_file": input_file,
        "output_location": output_location,
        "wrote_to_gcs": wrote_to_gcs,
        "environment": {
            "sa_available": sa_available,
            "gcs_bucket": gcs_bucket
        }
    }
    
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
