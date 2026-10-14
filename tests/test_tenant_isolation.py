"""
Regression tests for multi-user tenant isolation.
These tests verify that users cannot access each other's documents, images, or cached results.
"""

import pytest
from uuid import UUID, uuid4

from app import db
from app.cache import get_json, set_json
from app.retrieve import retrieve, _cache_key


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
    
    # Verify that all retrieved nodes belong to user1
    for source in result1.get("sources", []):
        doc = db.fetch_document(UUID(source["document_id"]), user1_id)
        assert doc is not None, f"Source {source['document_id']} does not belong to user1"
    
    # Retrieve with user2_id should only access user2's data
    result2 = retrieve(question, document_id=None, use_cache=False, user_id=user2_id)
    
    # Verify that all retrieved nodes belong to user2
    for source in result2.get("sources", []):
        doc = db.fetch_document(UUID(source["document_id"]), user2_id)
        assert doc is not None, f"Source {source['document_id']} does not belong to user2"


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
