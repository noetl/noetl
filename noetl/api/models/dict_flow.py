from sqlmodel import SQLModel, Field
from typing import Optional


class DictFlow(SQLModel, table=True):
    __tablename__ = "dict_flow"

    event_type: str = Field(primary_key=True, description="Event type triggering the dispatch")
    route_path: str = Field(description="API endpoint to call")
    http_method: str = Field(default="POST", description="HTTP method")
    module_name: str = Field(description="Domain component")

    unit_name: Optional[str] = Field(default=None,
                                     description="Execution scope this flow applies to (e.g., workflow, task, action)")

    route_module: Optional[str] = Field(default=None, description="Module defining the route")
    service_module: Optional[str] = Field(default=None, description="Service logic handler")
    model_module: Optional[str] = Field(default=None, description="SQLModel or ORM module used")
    table_name: Optional[str] = Field(default=None, description="Name of the table affected")

    description: Optional[str] = Field(default=None, description="Flow description")
    next_event: Optional[str] = Field(default=None, description="Next event expected from this call")