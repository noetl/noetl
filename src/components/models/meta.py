from typing import Optional
from src.components import Kind, BaseRepr


class Metadata(BaseRepr):
    """
    Metadata class.
    """

    def __init__(self, name: str, kind: Kind):
        """
        Initializes a Metadata.

        Args:
            name (str): The name.
            kind (Kind): The kind.
        """
        self.name: str = name
        self.kind: Kind = kind
        self.desc: Optional[str] = None
