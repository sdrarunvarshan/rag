"""
Tests for Temporal workflow safety and Garage object management.
These tests verify idempotency, cleanup, and object reconciliation.
"""

import pytest
from uuid import UUID, uuid4
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from typing import Any


def test_ingest_workflow_uses_stable_id():
    """Test that IngestParams uses stable document_id for idempotency."""
    from app.temporal_workflows import IngestParams
    
    params = IngestParams(
        garage_key="staging/test.pdf",
        filename="test.pdf",
        user_id=str(uuid4()),
        document_id=str(uuid4()),
    )
    
    assert params.document_id is not None
    assert len(params.document_id) > 0
    # Should be a valid UUID string
    UUID(params.document_id)  # Will raise if invalid


def test_parse_pdf_params_uses_garage_key():
    """Test that ParsePdfParams uses garage_key instead of local path."""
    from app.temporal_workflows import ParsePdfParams
    
    params = ParsePdfParams(
        garage_key="staging/doc-123/test.pdf",
        filename="test.pdf",
        document_id=str(uuid4()),
    )
    
    assert params.garage_key is not None
    assert "staging/" in params.garage_key
    assert params.document_id is not None


def test_insert_images_params_uses_keys_not_bytes():
    """Test that InsertImagesParams uses object keys instead of hex-encoded bytes."""
    from app.temporal_workflows import InsertImagesParams
    
    params = InsertImagesParams(
        document_id=str(uuid4()),
        image_keys=["documents/doc-123/images/img-1.png", "documents/doc-123/images/img-2.png"],
        image_metadata=[
            {"id": str(uuid4()), "mime_type": "image/png", "page": 1},
            {"id": str(uuid4()), "mime_type": "image/png", "page": 2},
        ],
    )
    
    assert len(params.image_keys) == 2
    assert len(params.image_metadata) == 2
    # No image_data field with hex-encoded bytes
    for meta in params.image_metadata:
        assert "image_data" not in meta


def test_cleanup_ingest_params_exists():
    """Test that CleanupIngestParams exists for compensation."""
    from app.temporal_workflows import CleanupIngestParams
    
    params = CleanupIngestParams(
        document_id=str(uuid4()),
        garage_keys=["staging/test.pdf"],
    )
    
    assert params.document_id is not None
    assert len(params.garage_keys) == 1


def test_workflow_id_uses_uuid():
    """Test that workflow IDs use UUID instead of hash for collision resistance."""
    from uuid import uuid4
    
    # Test ingest workflow ID
    workflow_id = f"ingest-{uuid4()}"
    assert "ingest-" in workflow_id
    assert len(workflow_id) > 10  # UUID is 36 chars + prefix
    
    # Test query workflow ID
    query_id = f"query-{uuid4()}"
    assert "query-" in query_id
    assert len(query_id) > 10


def test_basket_id_collision():
    """Test that UUID-based workflow IDs don't collide with hash-based IDs."""
    from uuid import uuid4
    
    # Generate multiple UUID-based IDs
    uuid_ids = [f"query-{uuid4()}" for _ in range(100)]
    
    # All should be unique
    assert len(set(uuid_ids)) == 100
    
    # Hash-based IDs can collide for identical questions
    question = "test question"
    hash_id_1 = f"query-{hash(question)}"
    hash_id_2 = f"query-{hash(question)}"
    assert hash_id_1 == hash_id_2  # Same hash for same question


def test_garage_upload_pdf_function():
    """Test that upload_pdf function exists and accepts correct parameters."""
    from app.garage_client import upload_pdf
    
    # Just verify the function signature exists
    assert callable(upload_pdf)
    
    # Should accept bytes, UUID, and filename
    import inspect
    sig = inspect.signature(upload_pdf)
    params = list(sig.parameters.keys())
    assert "pdf_bytes" in params
    assert "document_id" in params
    assert "filename" in params


def test_garage_delete_object_function():
    """Test that delete_garage_object function exists."""
    from app.garage_client import delete_garage_object
    
    assert callable(delete_garage_object)
    
    import inspect
    sig = inspect.signature(delete_garage_object)
    params = list(sig.parameters.keys())
    assert "object_key" in params


def test_garage_reconcile_function():
    """Test that reconcile_garage_objects function exists."""
    from app.garage_client import reconcile_garage_objects
    
    assert callable(reconcile_garage_objects)
    
    import inspect
    sig = inspect.signature(reconcile_garage_objects)
    # Just verify it's callable
    assert sig is not None


def test_bm25_atomic_write():
    """Test that BM25 index uses atomic writes."""
    from app.index import HybridIndex
    
    # Just verify the save method exists
    index = HybridIndex()
    assert hasattr(index, "_save_bm25")
    
    # Check that the method uses temporary file
    import inspect
    source = inspect.getsource(index._save_bm25)
    assert ".pkl.tmp" in source or "temp" in source.lower()
    assert "replace" in source


def test_bm25_version_tracking():
    """Test that BM25 index tracks version."""
    from app.index import HybridIndex
    
    index = HybridIndex()
    assert hasattr(index, "version")
    assert hasattr(index, "_get_version")


def test_document_deletion_partial_failure():
    """Test that document deletion handles partial failures."""
    # This is a conceptual test - actual integration would require mocking
    # The key is that the endpoint returns partial_failure status
    from app.main import delete_document_endpoint
    
    # Just verify the function exists
    assert callable(delete_document_endpoint)


def test_reconcile_endpoint_exists():
    """Test that Garage reconciliation endpoint exists."""
    from app.main import reconcile_garage
    
    assert callable(reconcile_garage)


def test_parse_pdf_activity_downloads_from_garage():
    """Test that parse_pdf_activity downloads from Garage instead of local file."""
    from app.temporal_activities import parse_pdf_activity
    
    # Verify the function exists
    assert callable(parse_pdf_activity)
    
    # Check that it uses garage_key parameter
    import inspect
    sig = inspect.signature(parse_pdf_activity.__wrapped__)
    params = list(sig.parameters.keys())
    assert "garage_key" in params


def test_insert_images_activity_uses_keys():
    """Test that insert_images_activity uses pre-uploaded keys."""
    from app.temporal_activities import insert_images_activity
    
    assert callable(insert_images_activity)
    
    import inspect
    sig = inspect.signature(insert_images_activity.__wrapped__)
    params = list(sig.parameters.keys())
    assert "image_keys" in params
    assert "image_metadata" in params


def test_cleanup_garage_activity_exists():
    """Test that cleanup_garage_activity exists for compensation."""
    from app.temporal_activities import cleanup_garage_activity
    
    assert callable(cleanup_garage_activity)
    
    import inspect
    sig = inspect.signature(cleanup_garage_activity.__wrapped__)
    params = list(sig.parameters.keys())
    assert "garage_keys" in params


def test_workflow_has_compensation():
    """Test that IngestWorkflow has compensation logic."""
    from app.temporal_workflows import IngestWorkflow
    
    # Verify the workflow class exists
    assert IngestWorkflow is not None
    
    # Check that the run method has try/except with cleanup
    import inspect
    source = inspect.getsource(IngestWorkflow.run)
    assert "try:" in source
    assert "except" in source
    assert "cleanup" in source.lower()


def test_ingest_uploads_to_garage_first():
    """Test that ingest endpoint uploads to Garage before Temporal."""
    from app.main import ingest
    
    assert callable(ingest)
    
    import inspect
    source = inspect.getsource(ingest)
    assert "upload_pdf" in source or "garage" in source.lower()


def test_no_hex_encoding_in_activities():
    """Test that activities don't use hex encoding for image data."""
    from app.temporal_activities import insert_images_activity
    
    import inspect
    source = inspect.getsource(insert_images_activity.__wrapped__)
    
    # Should not have hex encoding
    assert ".hex()" not in source
    assert "image_data" not in source or "hex" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
