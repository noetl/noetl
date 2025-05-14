from sqlmodel import SQLModel, Field
from typing import Optional

class DictOperand(SQLModel, table=True):
    __tablename__ = "dict_operand"
    operand_name: str = Field(primary_key=True)
    description: Optional[str] = None
