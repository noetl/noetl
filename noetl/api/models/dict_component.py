from sqlmodel import SQLModel, Field
from typing import Optional

class DictComponent(SQLModel, table=True):
    __tablename__ = "dict_component"

    component_name: str = Field(primary_key=True)
    route_module: Optional[str] = None
    schema_module: Optional[str] = None
    service_module: Optional[str] = None
    model_module: Optional[str] = None
    table_name: Optional[str] = None
    description: Optional[str] = None
