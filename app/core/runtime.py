"""Process-wide clients created during application startup."""

from __future__ import annotations

from temporalio.client import Client

temporal_client: Client | None = None
