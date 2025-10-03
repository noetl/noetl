from datetime import datetime
import json
from typing import Any, Type, TypeVar
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

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
    resource_path: str
    resource_type: str
    resource_version: str
    content: str | None = None
    layout: str | None = None
    meta: dict[str, Any]
    timestamp: datetime

    @model_validator(mode="after")
    def check_content_or_layout(cls, model):
        if not model.content and not model.layout:
            raise ValueError("Either 'content' or 'layout' must be provided.")
        return model
