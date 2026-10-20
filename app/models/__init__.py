"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.base import Base
from app.models.document import Document
from app.models.image import Image
from app.models.node import Node
from app.models.query_history import QueryHistory
from app.models.user import User
import app.models.document as _document
import app.models.image as _image
import app.models.node as _node

_document.Node = Node
_document.Image = Image
_node.Document = Document
_node.Image = Image
_image.Document = Document
_image.Node = Node

__all__ = [
    "Base",
    "Document",
    "Image",
    "Node",
    "QueryHistory",
    "User",
]
