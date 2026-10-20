"""Compatibility import. The database facade lives in app.database."""

from app.database.db import *  # noqa: F403
from app.database.db import __all__ as _all

__all__ = list(_all)
