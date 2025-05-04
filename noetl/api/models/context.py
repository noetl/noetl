from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSON


class Context(SQLModel, table=True):
    __tablename__ = "context"

    context_id: str = Field(primary_key=True, max_length=36)
    execution_id: str = Field(foreign_key="execution.execution_id", nullable=False)
    status: str = Field(default="PENDING", nullable=False)
    payload: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    started_at: datetime = Field(default=datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default_factory=datetime.now(timezone.utc))

    # Relationships
    execution_entry: Optional["Execution"] = Relationship(back_populates="contexts")
    results: List["Result"] = Relationship(back_populates="context_entry")
    events: List["Event"] = Relationship(back_populates="context_entry")

