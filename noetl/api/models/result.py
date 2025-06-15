from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, Dict, List
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Column
from datetime import datetime, timezone
from noetl.util.dro import generate_id

class Result(SQLModel, table=True):
    __tablename__ = "result"

    result_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
    # runtime_id: str = Field(foreign_key="runtime.runtime_id", nullable=False, max_length=36)
    # context_id: Optional[str] = Field(foreign_key="context.context_id", max_length=36)
    data: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    location: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON) )
    meta: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON) )
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default=datetime.now(timezone.utc))

    # runtime_entry: Optional["Runtime"] = Relationship(back_populates="result_entry")
    # context_entry: Optional["Context"] = Relationship(back_populates="result_entry")
