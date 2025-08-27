import os
import json
import yaml
import tempfile
import os
import json
import yaml
import tempfile
import psycopg
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.common import deep_merge, get_pgdb_connection, get_db_connection
from noetl.logger import setup_logger
from noetl.broker import Broker, execute_playbook_via_broker
from noetl.api import router as api_router
logger = setup_logger(__name__, include_location=True)

router = APIRouter()
router.include_router(api_router)

