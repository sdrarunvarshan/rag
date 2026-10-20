"""Failed ingests clean extracted images and partial rows. A finished document keeps its images."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.temporal_activities import failed_ingest_cleanup_keys, parse_pdf_activity
from app.temporal_workflows import IngestWorkflow

pytestmark = pytest.mark.unit


def test_failure_keys_include_staging_pdf_and_extracted_images():
    keys = failed_ingest_cleanup_keys("pdfs/doc.pdf", ["images/a.png", "images/b.png"])
    assert keys == ["pdfs/doc.pdf", "images/a.png", "images/b.png"]


def test_success_cleanup_list_is_only_the_staging_pdf():
    assert failed_ingest_cleanup_keys("pdfs/doc.pdf", None) == ["pdfs/doc.pdf"]


def test_parse_failure_after_image_upload_deletes_uploaded_keys(monkeypatch):
    deleted = []

    class Image:
        id = uuid4()
        image_data = b"img"
        mime_type = "image/png"
        page = 1
        caption = None
        node_id = None

    monkeypatch.setattr("app.temporal_activities.ensure_bucket", lambda: None)
    monkeypatch.setattr("app.temporal_activities.get_image_bytes", lambda key: (b"%PDF-1.4", "application/pdf"))
    monkeypatch.setattr("app.temporal_activities.parse_pdf", lambda path: ([], [Image(), Image()]))

    def upload_image(*args, **kwargs):
        upload_image.count += 1
        if upload_image.count > 1:
            raise RuntimeError("second upload failed")
        return "images/first.png"

    upload_image.count = 0
    monkeypatch.setattr("app.temporal_activities.upload_image", upload_image)
    monkeypatch.setattr("app.garage_client.delete_garage_object", lambda key: deleted.append(key))

    import asyncio

    with pytest.raises(RuntimeError, match="second upload failed"):
        asyncio.run(
            parse_pdf_activity(
                {"garage_key": "pdfs/doc.pdf", "filename": "paper.pdf", "document_id": str(uuid4())}
            )
        )

    assert deleted == ["images/first.png"]


def test_workflow_compensation_covers_images_and_partial_documents():
    import inspect

    source = inspect.getsource(IngestWorkflow.run)
    assert "failed_ingest_cleanup_keys" in source
    assert "delete_partial_document_activity" in source
    assert "image_keys" in source
    assert "document_inserted" in source
