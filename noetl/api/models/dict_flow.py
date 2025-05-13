from sqlmodel import SQLModel, Field
from typing import Optional


class DictFlow(SQLModel, table=True):
    __tablename__ = "dict_flow"

    event_type: str = Field(primary_key=True, description="Event Type e.g. ContextRegistration, ExecutionTrigger")
    description: Optional[str] = Field(default=None, description="What this event type represents or triggers")
    active: bool = Field(default=True, description="Whether this event type is currently supported")
