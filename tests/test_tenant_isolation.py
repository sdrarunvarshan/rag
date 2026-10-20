"""
Regression tests for multi-user tenant isolation.
These tests verify that users cannot access each other's documents, images, or cached results.
"""

import pytest
from uuid import UUID, uuid4

pytestmark = pytest.mark.integration

from app import db
from app.cache import get_json, set_json, track_cache_key, invalidate_user_cache
from app.retrieve import retrieve, _cache_key
from app.temporal_workflows import QueryParams, RetrieveParams


@pytest.fixture
def setup_test_users():
    """Create two test users for isolation testing."""
    # Clean up any existing test users
    user1 = db.get_user_by_email("user1@test.local")
    user2 = db.get_user_by_email("user2@test.local")
    
    if user1:
        db.delete_user(UUID(user1["id"]))
    if user2:
        db.delete_user(UUID(user2["id"]))
    
    # Create test users
    user1 = db.create_user("user1@test.local", "hashed_password_1", "User One")
    user2 = db.create_user("user2@test.local", "hashed_password_2", "User Two")
    
    yield {
        "user1_id": UUID(user1["id"]),
        "user2_id": UUID(user2["id"]),
    }
    
    # Cleanup
    db.delete_user(UUID(user1["id"]))
    db.delete_user(UUID(user2["id"]))


@pytest.fixture
def setup_test_documents(setup_test_users):
    """Create test documents for each user."""
    user1_id = setup_test_users["user1_id"]
    user2_id = setup_test_users["user2_id"]
    
    # Create documents for user1
    doc1_id = uuid4()
    db.insert_document(doc1_id, user1_id, "user1_document.pdf")
    
    # Create documents for user2
    doc2_id = uuid4()
    db.insert_document(doc2_id, user2_id, "user2_document.pdf")
    
    yield {
        "user1_id": user1_id,
        "user2_id": user2_id,
        "doc1_id": doc1_id,
        "doc2_id": doc2_id,
    }
    
    # Cleanup
    db.delete_document(doc1_id, user1_id)
    db.delete_document(doc2_id, user2_id)


def test_document_exists_user_isolation(setup_test_documents):
    """Test that document_exists correctly isolates by user."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    doc1_id = setup_test_documents["doc1_id"]
    doc2_id = setup_test_documents["doc2_id"]
    
    # User1 can access their own document
    assert db.document_exists(doc1_id, user1_id) is True
    
    # User1 cannot access user2's document
    assert db.document_exists(doc2_id, user1_id) is False
    
    # User2 can access their own document
    assert db.document_exists(doc2_id, user2_id) is True
    
    # User2 cannot access user1's document
    assert db.document_exists(doc1_id, user2_id) is False


def test_fetch_document_user_isolation(setup_test_documents):
    """Test that fetch_document correctly isolates by user."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    doc1_id = setup_test_documents["doc1_id"]
    doc2_id = setup_test_documents["doc2_id"]
    
    # User1 can fetch their own document
    doc1_for_user1 = db.fetch_document(doc1_id, user1_id)
    assert doc1_for_user1 is not None
    assert doc1_for_user1["filename"] == "user1_document.pdf"
    
    # User1 cannot fetch user2's document
    doc2_for_user1 = db.fetch_document(doc2_id, user1_id)
    assert doc2_for_user1 is None
    
    # User2 can fetch their own document
    doc2_for_user2 = db.fetch_document(doc2_id, user2_id)
    assert doc2_for_user2 is not None
    assert doc2_for_user2["filename"] == "user2_document.pdf"
    
    # User2 cannot fetch user1's document
    doc1_for_user2 = db.fetch_document(doc1_id, user2_id)
    assert doc1_for_user2 is None


def test_list_documents_user_isolation(setup_test_documents):
    """Test that list_documents only returns user's own documents."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    doc1_id = setup_test_documents["doc1_id"]
    doc2_id = setup_test_documents["doc2_id"]
    
    # User1's list should only contain their document
    user1_docs = db.list_documents(user1_id)
    assert len(user1_docs) == 1
    assert user1_docs[0]["id"] == str(doc1_id)
    
    # User2's list should only contain their document
    user2_docs = db.list_documents(user2_id)
    assert len(user2_docs) == 1
    assert user2_docs[0]["id"] == str(doc2_id)


def test_fetch_all_index_rows_user_isolation(setup_test_documents):
    """Test that fetch_all_index_rows isolates by user when user_id is provided."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    
    # Without user_id, returns all rows (WARNING: not tenant-isolated)
    all_rows = db.fetch_all_index_rows()
    assert len(all_rows) >= 0  # May be empty if no nodes
    
    # With user_id, returns only user's rows
    user1_rows = db.fetch_all_index_rows(user1_id)
    for row in user1_rows:
        # Verify that the document belongs to user1
        doc = db.fetch_document(UUID(row["document_id"]), user1_id)
        assert doc is not None
    
    user2_rows = db.fetch_all_index_rows(user2_id)
    for row in user2_rows:
        # Verify that the document belongs to user2
        doc = db.fetch_document(UUID(row["document_id"]), user2_id)
        assert doc is not None


def test_vector_search_user_isolation(setup_test_documents):
    """Test that vector_search isolates by user when user_id is provided."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    
    # Mock query embedding
    query_embedding = [0.1] * 768  # Typical embedding dimension
    
    # Without user_id, searches all nodes (WARNING: not tenant-isolated)
    all_results = db.vector_search(query_embedding, limit=10, document_id=None, user_id=None)
    
    # With user_id, searches only user's nodes
    user1_results = db.vector_search(query_embedding, limit=10, document_id=None, user_id=user1_id)
    for result in user1_results:
        # Verify that the document belongs to user1
        doc = db.fetch_document(UUID(result["document_id"]), user1_id)
        assert doc is not None, f"Result {result['document_id']} does not belong to user1"
    
    user2_results = db.vector_search(query_embedding, limit=10, document_id=None, user_id=user2_id)
    for result in user2_results:
        # Verify that the document belongs to user2
        doc = db.fetch_document(UUID(result["document_id"]), user2_id)
        assert doc is not None, f"Result {result['document_id']} does not belong to user2"


def test_cache_key_includes_user_id():
    """Test that cache keys include user_id for tenant isolation."""
    from app.retrieve import _cache_key
    
    question = "test question"
    document_id = str(uuid4())
    user1_id = uuid4()
    user2_id = uuid4()
    
    # Cache keys should differ by user_id
    key1 = _cache_key(question, document_id, user1_id)
    key2 = _cache_key(question, document_id, user2_id)
    
    assert key1 != key2, "Cache keys should differ for different users"
    
    # Cache keys should be same for same user
    key1_duplicate = _cache_key(question, document_id, user1_id)
    assert key1 == key1_duplicate, "Cache keys should be identical for same user"


def test_retrieve_with_user_isolation(setup_test_documents):
    """Test that retrieve function respects user_id for tenant isolation."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    
    question = "test question"
    
    # Retrieve with user1_id should only access user1's data
    result1 = retrieve(question, document_id=None, use_cache=False, user_id=user1_id)
    
    # Verify that all retrieved sections belong to user1
    for section in result1.get("sections", []):
        doc = db.fetch_document(UUID(section["document_id"]), user1_id)
        assert doc is not None, f"Section {section['document_id']} does not belong to user1"
    
    # Verify that all retrieved tables belong to user1
    for table in result1.get("tables", []):
        doc = db.fetch_document(UUID(table["document_id"]), user1_id)
        assert doc is not None, f"Table {table['document_id']} does not belong to user1"
    
    # Retrieve with user2_id should only access user2's data
    result2 = retrieve(question, document_id=None, use_cache=False, user_id=user2_id)
    
    # Verify that all retrieved sections belong to user2
    for section in result2.get("sections", []):
        doc = db.fetch_document(UUID(section["document_id"]), user2_id)
        assert doc is not None, f"Section {section['document_id']} does not belong to user2"
    
    # Verify that all retrieved tables belong to user2
    for table in result2.get("tables", []):
        doc = db.fetch_document(UUID(table["document_id"]), user2_id)
        assert doc is not None, f"Table {table['document_id']} does not belong to user2"


def test_image_belongs_to_user(setup_test_documents):
    """Test that image_belongs_to_user correctly checks ownership."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    doc1_id = setup_test_documents["doc1_id"]
    
    # Create a test image for user1's document
    image_id = uuid4()
    db.insert_image(
        image_id=image_id,
        document_id=doc1_id,
        node_id=None,
        minio_key="test/image.png",
        page=1,
        caption="Test image",
        mime_type="image/png",
    )
    
    try:
        # Image should belong to user1
        assert db.image_belongs_to_user(image_id, user1_id) is True
        
        # Image should not belong to user2
        assert db.image_belongs_to_user(image_id, user2_id) is False
    finally:
        # Cleanup
        with db.connect() as conn:
            conn.execute("DELETE FROM images WHERE id = %s", (image_id,))
            conn.commit()


def test_temporal_retrieve_params_includes_user_id():
    """Test that RetrieveParams includes user_id for Temporal workflow isolation."""
    user_id = uuid4()
    question = "test question"
    document_id = str(uuid4())
    
    # Create QueryParams with user_id
    query_params = QueryParams(
        question=question,
        document_id=document_id,
        user_id=str(user_id),
    )
    
    # Simulate workflow creating RetrieveParams
    retrieve_params = RetrieveParams(
        question=query_params.question,
        document_id=query_params.document_id,
        user_id=query_params.user_id,  # Must pass user_id for isolation
    )
    
    # Verify user_id is preserved
    assert retrieve_params.user_id == str(user_id), "user_id must be passed to RetrieveParams for tenant isolation"


def test_bm25_rebuild_includes_all_users(setup_test_documents):
    """Test that BM25 rebuild indexes all users' nodes, not just one user's nodes."""
    from app.index import hybrid_index
    
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    
    # Create some nodes for both users
    node1_id = uuid4()
    node2_id = uuid4()
    
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO nodes (id, document_id, node_type, heading, text, search_text, page, path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (node1_id, setup_test_documents["doc1_id"], "section", "User1 Section", "User1 content", "User1 content", 1, "1"),
        )
        conn.execute(
            "INSERT INTO nodes (id, document_id, node_type, heading, text, search_text, page, path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (node2_id, setup_test_documents["doc2_id"], "section", "User2 Section", "User2 content", "User2 content", 1, "1"),
        )
        conn.commit()
    
    try:
        # Rebuild BM25 with user1_id (should be ignored)
        hybrid_index.rebuild_bm25(user_id=user1_id)
        
        # Verify that the index contains both users' nodes
        # The rebuild_bm25 function should ignore user_id and index all nodes
        assert node1_id in hybrid_index.ids or str(node1_id) in hybrid_index.ids, "Index should contain user1's node"
        assert node2_id in hybrid_index.ids or str(node2_id) in hybrid_index.ids, "Index should contain user2's node"
        
        # Also verify the document_ids are present
        assert str(setup_test_documents["doc1_id"]) in hybrid_index.document_ids, "Index should contain user1's document"
        assert str(setup_test_documents["doc2_id"]) in hybrid_index.document_ids, "Index should contain user2's document"
    finally:
        # Cleanup
        with db.connect() as conn:
            conn.execute("DELETE FROM nodes WHERE id IN (%s, %s)", (node1_id, node2_id))
            conn.commit()


def test_cache_invalidation_with_tracking(setup_test_documents):
    """Test that cache keys are tracked and can be invalidated by user_id."""
    user1_id = setup_test_documents["user1_id"]
    user2_id = setup_test_documents["user2_id"]
    
    question = "test question"
    document_id = str(uuid4())
    
    # Generate cache keys for both users
    key1 = _cache_key(question, document_id, user1_id)
    key2 = _cache_key(question, document_id, user2_id)
    
    # Track cache keys for both users
    track_cache_key(str(user1_id), key1)
    track_cache_key(str(user2_id), key2)
    
    # Set cache entries
    set_json(key1, {"answer": "user1 answer"})
    set_json(key2, {"answer": "user2 answer"})
    
    # Verify both entries exist
    assert get_json(key1) is not None, "User1 cache entry should exist"
    assert get_json(key2) is not None, "User2 cache entry should exist"
    
    # Invalidate user1's cache
    invalidate_user_cache(str(user1_id))
    
    # Verify user1's entry is deleted but user2's remains
    assert get_json(key1) is None, "User1 cache entry should be invalidated"
    assert get_json(key2) is not None, "User2 cache entry should remain"
    
    # Cleanup
    invalidate_user_cache(str(user2_id))


def test_bm25_text_change_triggers_rebuild(setup_test_documents):
    """Test that BM25 index rebuilds when text content changes."""
    from app.index import hybrid_index
    
    user1_id = setup_test_documents["user1_id"]
    doc1_id = setup_test_documents["doc1_id"]
    
    # Create a node with initial text
    node_id = uuid4()
    initial_text = "Initial content for testing"
    
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO nodes (id, document_id, node_type, heading, text, search_text, page, path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (node_id, doc1_id, "section", "Test Section", initial_text, initial_text, 1, "1"),
        )
        conn.commit()
    
    try:
        # Rebuild BM25 index
        hybrid_index.rebuild_bm25()
        initial_fingerprint = hybrid_index._get_corpus_fingerprint()
        
        # Modify the text content without changing node ID
        modified_text = "Modified content for testing"
        with db.connect() as conn:
            conn.execute(
                "UPDATE nodes SET text = %s, search_text = %s WHERE id = %s",
                (modified_text, modified_text, node_id),
            )
            conn.commit()
        
        # Check that fingerprint changed
        modified_fingerprint = hybrid_index._get_corpus_fingerprint()
        assert initial_fingerprint != modified_fingerprint, "Fingerprint should change when text changes"
        
        # Reload and verify it triggers rebuild
        hybrid_index.load_or_rebuild()
        assert hybrid_index.version == modified_fingerprint, "Index should have new fingerprint after rebuild"
        
        # Test edge case: text with delimiters shouldn't cause ambiguity
        text_with_delimiters = "Chapter 1: Introduction | Section A"
        with db.connect() as conn:
            conn.execute(
                "UPDATE nodes SET text = %s, search_text = %s WHERE id = %s",
                (text_with_delimiters, text_with_delimiters, node_id),
            )
            conn.commit()
        
        # Should still generate valid fingerprint without ambiguity
        delimiter_fingerprint = hybrid_index._get_corpus_fingerprint()
        assert delimiter_fingerprint != modified_fingerprint, "Fingerprint should change with delimiter-containing text"
    finally:
        # Cleanup
        with db.connect() as conn:
            conn.execute("DELETE FROM nodes WHERE id = %s", (node_id,))
            conn.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
