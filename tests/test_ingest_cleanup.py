"""Ingest failure paths clean temporary files and the staging PDF without hiding the original error."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import ingest_service

pytestmark = pytest.mark.unit


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(request_id="req-1"))


def _file() -> SimpleNamespace:
    return SimpleNamespace(filename="paper.pdf")


@pytest.mark.asyncio
async def test_streaming_failure_does_not_touch_garage(monkeypatch, tmp_path):
    deleted = {"called": False}

    async def stream_upload(*args, **kwargs):
        raise HTTPException(status_code=413, detail="too large")

    monkeypatch.setattr(ingest_service, "ping", lambda: True)
    monkeypatch.setattr(ingest_service, "stream_upload_to_disk", stream_upload)
    monkeypatch.setattr(
        "app.garage_client.delete_garage_object",
        lambda key: deleted.__setitem__("called", True),
    )

    with pytest.raises(HTTPException) as exc:
        await ingest_service.ingest(_request(), _file(), {"id": "user"})

    assert exc.value.status_code == 413
    assert deleted["called"] is False


@pytest.mark.asyncio
async def test_garage_upload_failure_removes_the_local_file(monkeypatch, tmp_path):
    local = tmp_path / "upload.pdf"
    local.write_bytes(b"%PDF-1.4")

    async def stream_upload(*args, **kwargs):
        return local

    def upload_pdf(*args, **kwargs):
        raise RuntimeError("garage down")

    monkeypatch.setattr(ingest_service, "ping", lambda: True)
    monkeypatch.setattr(ingest_service, "stream_upload_to_disk", stream_upload)
    monkeypatch.setattr("app.garage_client.upload_pdf", upload_pdf)

    with pytest.raises(HTTPException) as exc:
        await ingest_service.ingest(_request(), _file(), {"id": "user"})

    assert exc.value.status_code == 500
    assert "garage down" in exc.value.detail
    assert not local.exists()


@pytest.mark.asyncio
async def test_temporal_failure_deletes_staging_without_hiding_the_error(monkeypatch, tmp_path):
    local = tmp_path / "upload.pdf"
    local.write_bytes(b"%PDF-1.4")
    removed = []

    class Client:
        async def execute_workflow(self, *args, **kwargs):
            raise RuntimeError("temporal down")

    async def stream_upload(*args, **kwargs):
        return local

    monkeypatch.setattr(ingest_service, "ping", lambda: True)
    monkeypatch.setattr(ingest_service, "stream_upload_to_disk", stream_upload)
    monkeypatch.setattr("app.garage_client.upload_pdf", lambda *args, **kwargs: "staging/paper.pdf")
    monkeypatch.setattr(ingest_service.runtime, "temporal_client", Client())
    monkeypatch.setattr("app.garage_client.delete_garage_object", lambda key: removed.append(key))

    with pytest.raises(HTTPException) as exc:
        await ingest_service.ingest(_request(), _file(), {"id": "user"})

    assert "temporal down" in exc.value.detail
    assert removed == ["staging/paper.pdf"]
    assert not local.exists()


@pytest.mark.asyncio
async def test_direct_ingest_failure_cleans_staging_and_temp_files(monkeypatch, tmp_path):
    local = tmp_path / "upload.pdf"
    local.write_bytes(b"%PDF-1.4")
    removed = []

    async def stream_upload(*args, **kwargs):
        return local

    monkeypatch.setattr(ingest_service, "ping", lambda: True)
    monkeypatch.setattr(ingest_service, "stream_upload_to_disk", stream_upload)
    monkeypatch.setattr("app.garage_client.upload_pdf", lambda *args, **kwargs: "staging/paper.pdf")
    monkeypatch.setattr(ingest_service.runtime, "temporal_client", None)
    monkeypatch.setattr("app.garage_client.get_image_bytes", lambda key: (b"%PDF-1.4", "application/pdf"))
    monkeypatch.setattr(ingest_service, "ingest_pdf", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parse failed")))
    monkeypatch.setattr("app.garage_client.delete_garage_object", lambda key: removed.append(key))

    with pytest.raises(HTTPException) as exc:
        await ingest_service.ingest(_request(), _file(), {"id": "user"})

    assert "parse failed" in exc.value.detail
    assert removed == ["staging/paper.pdf"]
    assert not local.exists()


@pytest.mark.asyncio
async def test_cleanup_failure_after_success_does_not_fail_the_ingest(monkeypatch, tmp_path):
    local = tmp_path / "upload.pdf"
    local.write_bytes(b"%PDF-1.4")

    async def stream_upload(*args, **kwargs):
        return local

    monkeypatch.setattr(ingest_service, "ping", lambda: True)
    monkeypatch.setattr(ingest_service, "stream_upload_to_disk", stream_upload)
    monkeypatch.setattr("app.garage_client.upload_pdf", lambda *args, **kwargs: "staging/paper.pdf")
    monkeypatch.setattr(ingest_service.runtime, "temporal_client", None)
    monkeypatch.setattr("app.garage_client.get_image_bytes", lambda key: (b"%PDF-1.4", "application/pdf"))
    monkeypatch.setattr(ingest_service, "ingest_pdf", lambda *args, **kwargs: {"document_id": "doc"})

    def delete_garage_object(key):
        raise RuntimeError("delete failed")

    monkeypatch.setattr("app.garage_client.delete_garage_object", delete_garage_object)

    result = await ingest_service.ingest(_request(), _file(), {"id": "user"})

    assert result == {"document_id": "doc"}
    assert not local.exists()
