from datetime import datetime
import json
from typing import Any, Type, TypeVar
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator, Field

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


class AppBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)


T = TypeVar("T", bound=BaseModel)


def transform(class_constructor: Type[T], arg: dict) -> T:
    """
    Generic function to transform a dict into a Pydantic model instance. with error logging.

    Args:
        class_constructor: Any Pydantic model class.
        arg: Dictionary of data to pass to the model.

    Returns:
        An instance of the model.

    Raises:
        ValidationError: If the data does not conform to the model.
    """
    try:
        return class_constructor(**arg)
    except ValidationError as e:
        logger.error(
            f"{class_constructor.__name__} Validation error: {json.dumps(e.errors(include_input=False, include_url=False))}")
        raise


class PlaybookResourceResponse(AppBaseModel):
    """Response model for playbook resource"""
    path: str
    kind: str
    version: int
    content: str | None = None
    layout: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    meta: dict[str, Any]
    created_at: datetime

    @model_validator(mode="after")
    def check_content_or_layout(cls, model):
        if not model.content and not model.layout:
            raise ValueError("Either 'content' or 'layout' must be provided.")
        return model


class CatalogEntryResponse(AppBaseModel):
    """Response model for a single catalog entry"""
    path: str
    kind: str
    version: int
    content: str | None = None
    layout: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime


class CatalogListResponse(AppBaseModel):
    """Response model for catalog list endpoint"""
    entries: list[CatalogEntryResponse]


class PlaybookSummaryResponse(AppBaseModel):
    """Response model for playbook summary (legacy /catalog/playbooks endpoint)"""
    id: str
    name: str
    kind: str
    version: int
    meta: dict[str, Any] | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    status: str = "active"
    tasks_count: int = 0
