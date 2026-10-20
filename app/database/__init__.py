"""Database access facade."""

from app.database.db import *  # noqa: F403
from app.database.db import __all__ as _all

__all__ = list(_all)
