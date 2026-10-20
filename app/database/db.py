"""Compatibility facade. New code should import from app.repositories."""

from app.repositories import *  # noqa: F403
from app.repositories import __all__ as _all

__all__ = list(_all)
