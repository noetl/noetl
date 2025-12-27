#!/usr/bin/env python3
"""
Simple data processor script for testing K8s job execution.

This script demonstrates:
- Receiving arguments as JSON
- Accessing environment variables (including OAuth2 credentials from keychain)
- Processing data with configurable mode
- Writing results to GCS using google-cloud-storage library
- Outputting structured results
- **PROPER ERROR HANDLING with exit codes**
"""

import sys
import json
import os
import urllib.request
import urllib.error
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def main():
    errors = []

    try:
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

        logger.info(f"[DATA PROCESSOR] Starting | mode={mode} | input={input_file} | output_bucket={output_bucket} | sa_available={sa_available}")
        if sa_available:
            logger.debug(f"[DATA PROCESSOR] SA type={type(gcp_sa_json)} | length={len(gcp_sa_json)[:150]} | gcs_bucket={gcs_bucket}")
        logger.info(f"[DATA PROCESSOR] GCP Project from env: {gcp_project}")

        # Simulate processing
        records_processed = 1000
        logger.info(f"[DATA PROCESSOR] Processed {records_processed} records")

        # Write results to GCS if service account is available
        output_location = f"gs://{output_bucket}/results/output.csv"
        wrote_to_gcs = False

        if sa_available:
            try:
                logger.info(f"[DATA PROCESSOR] Attempting to write to GCS: {output_location}")

                # Generate CSV content
                csv_content = "id,name,value,timestamp\n"
                for i in range(1, min(records_processed + 1, 11)):  # First 10 rows as sample
                    csv_content += f"{i},record_{i},{i * 100},{datetime.utcnow().isoformat()}\n"

                # Parse service account JSON
                logger.debug(f"[DATA PROCESSOR] Parsing SA JSON | length={len(gcp_sa_json)}")

                # Try to detect if it's already a dict (shouldn't happen with env var, but check)
                if isinstance(gcp_sa_json, dict):
                    logger.debug(f"[DATA PROCESSOR] SA is already a dict, using directly")
                    sa_info = gcp_sa_json
                else:
                    # It's a string, try to parse
                    logger.debug(f"[DATA PROCESSOR] SA is string, parsing with json.loads()")
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

                logger.info(f"[DATA PROCESSOR] Generated access token from service account")

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

                with urllib.request.urlopen(request_obj) as response:
                    if response.status in (200, 201):
                        wrote_to_gcs = True
                        logger.info(f"[DATA PROCESSOR] ✓ Uploaded {len(csv_content)} bytes to {output_location}")
                    else:
                        error_msg = f"HTTP {response.status}"
                        errors.append(f"GCS upload failed: {error_msg}")
                        logger.error(f"[DATA PROCESSOR] ✗ Failed to write to GCS: {error_msg}")

            except urllib.error.HTTPError as e:
                error_msg = f"HTTP Error: {e.code} - {e.read().decode('utf-8')}"
                errors.append(error_msg)
                logger.error(f"[DATA PROCESSOR] ✗ {error_msg}")
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                errors.append(f"GCS upload failed: {error_msg}")
                logger.error(f"[DATA PROCESSOR] ✗ Failed to write to GCS: {error_msg}")
                import traceback
                traceback.print_exc()
        else:
            logger.warning(f"[DATA PROCESSOR] ⚠ Service account not available, skipping GCS upload")

        # Output result as JSON
        result = {
            "status": "completed" if not errors else "failed",
            "records_processed": records_processed,
            "input_file": input_file,
            "output_location": output_location,
            "wrote_to_gcs": wrote_to_gcs,
            "errors": errors if errors else None,
            "environment": {
                "sa_available": sa_available,
                "gcs_bucket": gcs_bucket
            }
        }

        print(json.dumps(result))

        # EXIT WITH PROPER CODE
        if errors:
            logger.error(f"[DATA PROCESSOR] ✗ Exiting with code 1 due to {len(errors)} error(s)")
            return 1
        else:
            return 0

    except Exception as e:
        logger.critical(f"[DATA PROCESSOR] ✗ FATAL ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    sys.exit(main())
