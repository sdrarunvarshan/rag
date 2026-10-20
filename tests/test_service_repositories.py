"""Service workflows call repositories with the authenticated user's id."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.schemas.auth import UserLogin, UserRegister
from app.schemas.query import QueryRequest
from app.services import auth_service, document_service, query_service

USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_DOC = UUID("22222222-2222-2222-2222-222222222222")


def _user() -> dict:
    return {"id": str(USER_ID), "email": "owner@example.com"}


def test_list_documents_is_scoped_to_the_authenticated_user(monkeypatch):
    seen = {}

    monkeypatch.setattr(document_service, "ping", lambda: True)

    def list_documents(user_id):
        seen["user_id"] = user_id
        return []

    monkeypatch.setattr(document_service, "list_documents", list_documents)

    result = document_service.list_user_documents(_user())

    assert seen["user_id"] == USER_ID
    assert result == {"documents": []}


def test_other_users_document_cannot_be_deleted(monkeypatch):
    monkeypatch.setattr(document_service, "ping", lambda: True)
    monkeypatch.setattr(document_service, "document_exists", lambda document_id, user_id: False)
    deleted = {"called": False}
    monkeypatch.setattr(
        document_service,
        "delete_document",
        lambda *args: deleted.__setitem__("called", True),
    )

    with pytest.raises(HTTPException) as exc:
        document_service.delete_document_endpoint(str(OTHER_DOC), _user())

    assert exc.value.status_code == 404
    assert deleted["called"] is False


def test_delete_removes_owned_document_and_invalidates_cache(monkeypatch):
    calls = []

    monkeypatch.setattr(document_service, "ping", lambda: True)
    monkeypatch.setattr(
        document_service,
        "document_exists",
        lambda document_id, user_id: user_id == USER_ID and document_id == OTHER_DOC,
    )
    monkeypatch.setattr(document_service, "delete_document_images", lambda document_id: calls.append(("garage", document_id)))
    monkeypatch.setattr(
        document_service,
        "delete_document",
        lambda document_id, user_id: calls.append(("db", document_id, user_id)) or True,
    )
    monkeypatch.setattr(document_service.hybrid_index, "rebuild_bm25", lambda: calls.append(("index",)))
    monkeypatch.setattr(
        document_service.cache,
        "invalidate_user_cache",
        lambda user_id: calls.append(("cache", user_id)),
    )

    result = document_service.delete_document_endpoint(str(OTHER_DOC), _user())

    assert result["status"] == "deleted"
    assert ("db", OTHER_DOC, USER_ID) in calls
    assert ("cache", str(USER_ID)) in calls


def test_image_lookup_requires_the_authenticated_owner(monkeypatch):
    image_id = uuid4()
    seen = {}

    monkeypatch.setattr(document_service, "ping", lambda: True)
    monkeypatch.setattr(
        document_service,
        "fetch_image",
        lambda image_id, user_id: seen.update(image_id=image_id, user_id=user_id) or None,
    )

    with pytest.raises(HTTPException) as exc:
        document_service.load_image(str(image_id), _user())

    assert exc.value.status_code == 404
    assert seen == {"image_id": image_id, "user_id": USER_ID}


async def test_query_history_is_saved_for_the_authenticated_user(monkeypatch):
    saved = {}

    monkeypatch.setattr(query_service, "ping", lambda: True)
    monkeypatch.setattr(query_service, "document_exists", lambda document_id, user_id: True)
    monkeypatch.setattr(query_service.runtime, "temporal_client", None)
    monkeypatch.setattr(
        query_service,
        "run_rag_pipeline",
        lambda question, document_id, user_id: {
            "answer": "grounded",
            "cached": False,
            "sources": [{"id": "n1"}],
            "context": "context",
            "flow": {},
        },
    )
    monkeypatch.setattr(query_service, "save_query_history", lambda **kwargs: saved.update(kwargs) or uuid4())

    request = SimpleNamespace(state=SimpleNamespace(request_id="req-1"))
    body = QueryRequest(question="What is the title?", document_id=str(OTHER_DOC))

    result = await query_service.answer_query(request, body, _user())

    assert result.answer == "grounded"
    assert saved["user_id"] == USER_ID
    assert saved["document_id"] == OTHER_DOC
    assert saved["question"] == "What is the title?"


def test_query_history_delete_is_scoped_to_the_owner(monkeypatch):
    query_id = uuid4()
    seen = {}

    monkeypatch.setattr(document_service, "ping", lambda: True)
    monkeypatch.setattr(
        document_service,
        "delete_query_history",
        lambda query_uuid, user_id: seen.update(query_id=query_uuid, user_id=user_id) or False,
    )

    with pytest.raises(HTTPException) as exc:
        document_service.remove_query_history(str(query_id), _user())

    assert exc.value.status_code == 404
    assert seen == {"query_id": query_id, "user_id": USER_ID}


def test_query_rejects_a_document_the_user_does_not_own(monkeypatch):
    monkeypatch.setattr(query_service, "document_exists", lambda document_id, user_id: False)

    with pytest.raises(HTTPException) as exc:
        query_service.resolved_document_id(str(OTHER_DOC), str(USER_ID))

    assert exc.value.status_code == 404


def test_register_creates_the_user_through_the_repository(monkeypatch):
    monkeypatch.setattr(auth_service, "ping", lambda: True)
    monkeypatch.setattr(auth_service, "get_user_by_email", lambda email: None)
    created = {}

    def create_user(email, hashed_password, full_name=None):
        created["email"] = email
        created["full_name"] = full_name
        return {"id": str(USER_ID), "email": email, "full_name": full_name, "created_at": None}

    monkeypatch.setattr(auth_service, "create_user", create_user)

    token = auth_service.register_user(UserRegister(email="owner@example.com", password="secret1", full_name="Owner"))

    assert created["email"] == "owner@example.com"
    assert token.user.id == str(USER_ID)


def test_login_reads_the_user_from_the_repository(monkeypatch):
    monkeypatch.setattr(auth_service, "ping", lambda: True)
    monkeypatch.setattr(auth_service, "verify_password", lambda plain, hashed: hashed == "stored" and plain == "secret1")
    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        lambda email: {
            "id": str(USER_ID),
            "email": email,
            "hashed_password": "stored",
            "full_name": None,
            "created_at": None,
        },
    )

    token = auth_service.login_user(UserLogin(email="owner@example.com", password="secret1"))

    assert token.user.email == "owner@example.com"
