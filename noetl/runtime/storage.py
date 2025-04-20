import json
import datetime
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import sqlite3

class StorageInterface(ABC):
    @abstractmethod
    def record_event(self, job_id: str, event_type: str, context: Optional[dict] = None,
                     step_id: Optional[str] = None, task_id: Optional[str] = None,
                     action_id: Optional[str] = None,
                     step_loop_id: str = "1", task_loop_id: str = "1", action_loop_id: str = "1"):
        pass

    @abstractmethod
    def get_events(self, job_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def reconstruct_state(self, job_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def close(self):
        pass

class JSONAppendStorage(StorageInterface):

    def __init__(self, file_path: str):
        self.file_path = file_path
        open(self.file_path, "a").close()

    def record_event(self, job_id: str, event_type: str, context: Optional[dict] = None,
                     step_id: Optional[str] = None, task_id: Optional[str] = None,
                     action_id: Optional[str] = None,
                     step_loop_id: str = "1", task_loop_id: str = "1", action_loop_id: str = "1"):
        event = {
            "job_id": job_id,
            "event_type": event_type,
            "context": context or {},
            "step_id": step_id,
            "task_id": task_id,
            "action_id": action_id,
            "step_loop_id": step_loop_id,
            "task_loop_id": task_loop_id,
            "action_loop_id": action_loop_id,
            "created_at":  datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        }
        with open(self.file_path, "a") as f:
            f.write(json.dumps(event) + "\n")

    def get_events(self, job_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        events = []
        with open(self.file_path, "r") as f:
            for line in f:
                event = json.loads(line.strip())
                if event["job_id"] == job_id and (event_type is None or event["event_type"] == event_type):
                    events.append(event)
        return events

    def reconstruct_state(self, job_id: str) -> Dict[str, Any]:
        events = self.get_events(job_id)
        state = {"job_id": job_id, "steps": {}, "context": {}}
        for event in events:
            event_type = event["event_type"]
            context = event["context"]
            if event_type == "START_JOB":
                state["start_time"] = event["created_at"]
            elif event_type == "UPDATE_CONTEXT":
                state["context"].update(context)
            elif event_type == "START_STEP":
                step_id = event["step_id"]
                step_loop_id = event["step_loop_id"]
                state["steps"].setdefault(step_id, {"tasks": {}, "loops": {}})
                state["steps"][step_id]["loops"].setdefault(step_loop_id, {"state": "active"})
            elif event_type == "START_TASK":
                step_id = event["step_id"]
                step_loop_id = event["step_loop_id"]
                task_id = event["task_id"]
                task_loop_id = event["task_loop_id"]
                tasks = state["steps"][step_id]["loops"][step_loop_id].setdefault("tasks", {})
                tasks.setdefault(task_id, {"loops": {}})
                tasks[task_id]["loops"].setdefault(task_loop_id, {"state": "active"})
            elif event_type == "COMPLETE_TASK":
                step_id = event["step_id"]
                step_loop_id = event["step_loop_id"]
                task_id = event["task_id"]
                task_loop_id = event["task_loop_id"]
                state["steps"][step_id]["loops"][step_loop_id]["tasks"][task_id]["loops"][task_loop_id][
                    "state"] = "completed"
        return state

    def close(self):
        pass

class SQLiteStorage(StorageInterface):

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.initialize_schema()

    def initialize_schema(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    step_id TEXT,
                    task_id TEXT,
                    action_id TEXT,
                    step_loop_id TEXT DEFAULT '1',
                    task_loop_id TEXT DEFAULT '1',
                    action_loop_id TEXT DEFAULT '1',
                    event_type TEXT NOT NULL,
                    context JSON,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def record_event(self, job_id: str, event_type: str, context: Optional[dict] = None,
                     step_id: Optional[str] = None, task_id: Optional[str] = None,
                     action_id: Optional[str] = None,
                     step_loop_id: str = "1", task_loop_id: str = "1", action_loop_id: str = "1"):
        with self.conn:
            self.conn.execute('''
                INSERT INTO events (job_id, event_type, step_id, task_id, action_id, step_loop_id, task_loop_id, action_loop_id, context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, json(?))
            ''', (job_id, event_type, step_id, task_id, action_id, step_loop_id, task_loop_id, action_loop_id,
                  json.dumps(context or {})))

    def get_events(self, job_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        if event_type:
            cursor.execute('SELECT * FROM events WHERE job_id = ? AND event_type = ? ORDER BY created_at',
                           (job_id, event_type))
        else:
            cursor.execute('SELECT * FROM events WHERE job_id = ? ORDER BY created_at', (job_id,))
        return [dict(row) for row in cursor.fetchall()]

    def reconstruct_state(self, job_id: str) -> Dict[str, Any]:
        events = self.get_events(job_id)
        return JSONAppendStorage("").reconstruct_state(events)

    def close(self):
        self.conn.close()

class StorageFactory:

    @staticmethod
    def get_storage(config: dict) -> StorageInterface:
        if config["storage_type"] == "json":
            return JSONAppendStorage(config["file_path"])
        elif config["storage_type"] == "sqlite":
            return SQLiteStorage(config["sqlite_path"])
        else:
            raise ValueError(f"Unsupported storage type: {config['storage_type']}")
