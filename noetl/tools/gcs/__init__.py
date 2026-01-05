"""
GCS (Google Cloud Storage) plugin for NoETL.

Provides file upload capabilities to Google Cloud Storage with service account authentication.
"""

from noetl.tools.gcs.executor import execute_gcs_task

__all__ = ['execute_gcs_task']
