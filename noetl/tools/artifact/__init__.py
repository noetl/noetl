"""
Artifact tool for loading externalized results from storage.

This module provides functionality to retrieve results that were externalized
to artifact storage (S3, GCS, local filesystem) during workflow execution.

The artifact.get action loads results by:
1. Looking up the result_ref in result_index table
2. Resolving the logical_uri to actual storage location
3. Loading and deserializing the result data
"""

from noetl.tools.artifact.executor import (
    execute_artifact_task,
    execute_artifact_get,
    execute_artifact_put,
)

__all__ = [
    "execute_artifact_task",
    "execute_artifact_get", 
    "execute_artifact_put",
]
