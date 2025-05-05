from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSON


class Execution(SQLModel, table=True):
    __tablename__ = "execution"


    execution_id: str = Field(primary_key=True, max_length=36)
    registry_id: str = Field(foreign_key="registry.registry_id", nullable=False, max_length=36)
    status: str = Field(default="READY", nullable=False)
    started_at: datetime = Field(default=datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default_factory=datetime.now(timezone.utc))
    logs: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))

    registry_entry: Optional["Registry"] = Relationship(back_populates="executions")
    contexts: List["Context"] = Relationship(back_populates="execution_entry")
    results: List["Result"] = Relationship(back_populates="execution_entry")
    events: List["Event"] = Relationship(back_populates="execution_entry")
