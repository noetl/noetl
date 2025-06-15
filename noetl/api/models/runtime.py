# from sqlmodel import SQLModel, Field, Relationship
# from typing import Optional, List, Dict
# from datetime import datetime, timezone
# from sqlalchemy import Column
# from sqlalchemy.dialects.postgresql import JSON
# from noetl.util.dro import generate_id
#
# class Runtime(SQLModel, table=True):
#     __tablename__ = "runtime"
#
#
#     runtime_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
#     workload_id: str = Field(foreign_key="workload.workload_id", nullable=False, max_length=36)
#     status: str = Field(default="READY", nullable=False)
#     started_at: datetime = Field(default=datetime.now(timezone.utc))
#     completed_at: Optional[datetime] = Field(default=datetime.now(timezone.utc))
#     logs: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
#     labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
#     tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
#
#     workload_entry: Optional["Workload"] = Relationship(back_populates="runtime_entry")
#     context_entry: List["Context"] = Relationship(back_populates="runtime_entry")
#     result_entry: List["Result"] = Relationship(back_populates="runtime_entry")
#     event_entry: List["Event"] = Relationship(back_populates="runtime_entry")
