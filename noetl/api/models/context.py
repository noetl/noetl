# from sqlmodel import SQLModel, Field, Relationship
# from typing import Optional, List, Dict
# from datetime import datetime, timezone
# from sqlalchemy import Column
# from sqlalchemy.dialects.postgresql import JSON
# from noetl.util.dro import generate_id
#
# class Context(SQLModel, table=True):
#     __tablename__ = "context"
#
#     context_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
#     runtime_id: str = Field(foreign_key="runtime.runtime_id", nullable=False, max_length=36)
#     status: str = Field(default="PENDING", nullable=False)
#     payload: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
#     meta: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
#     labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
#     tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
#     started_at: datetime = Field(default=datetime.now(timezone.utc))
#     completed_at: Optional[datetime] = Field(default=datetime.now(timezone.utc))
#
#     # Relationships
#     runtime_entry: Optional["Runtime"] = Relationship(back_populates="context_entry")
#     result_entry: List["Result"] = Relationship(back_populates="context_entry")
#     event_entry: List["Event"] = Relationship(back_populates="context_entry")
