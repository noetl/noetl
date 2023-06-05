from typing import Optional
from src.components import Kind, BaseRepr


class Metadata(BaseRepr):
    """
    Metadata class.
    """

    def __init__(self,
                 name: str,
                 kind: Kind,
                 version: str,
                 instance_id: Optional[str] = None,
                 desc: Optional[str] = None,
                 ):
        self.name: str = name
        self.kind: Kind = kind
        self.version: str = version
        self.instance_id = instance_id
        self.desc: Optional[str] = desc

    def get_instance_id(self):
        return self.instance_id

    def set_instance_id(self, instance_id: str):
        self.instance_id = instance_id
