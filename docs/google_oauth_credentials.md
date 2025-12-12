# Generate Google Application Default Credentials (ADC) with gcloud

Application Default Credentials (ADC) are user credentials that Google client libraries and tools automatically discover and use on your machine. The `gcloud` CLI can generate and manage these for you.

Important:
- Do not commit ADC files to source control.
- ADC for a user account is stored as an `authorized_user` JSON at a well-known path on your machine.

## Quick start (macOS/Linux)

1) Login to create/update ADC:
