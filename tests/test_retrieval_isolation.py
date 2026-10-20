"""Tenant-scoped retrieval must not expand into another user's nodes or images."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest

from app.repositories.image_repository import fetch_images_by_node
from app.repositories.node_repository import fetch_children, fetch_node, fetch_tables_under
from app.retrieve import expand_hit, retrieve_images

pytestmark = pytest.mark.unit

OWNER = uuid4()
OTHER = uuid4()
NODE = uuid4()


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, captured: dict):
        self.captured = captured

    def execute(self, sql, params=None):
        self.captured["sql"] = " ".join(sql.split())
        self.captured["params"] = params
        return _Result()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_connect(monkeypatch, module: str):
    captured: dict = {}

    @contextmanager
    def connect():
        yield _Conn(captured)

    monkeypatch.setattr(f"{module}.connect", connect)
    return captured


def test_fetch_node_sql_requires_the_owner(monkeypatch):
    captured = _patch_connect(monkeypatch, "app.repositories.node_repository")
    assert fetch_node(NODE, OWNER) is None
    assert "d.user_id = %s" in captured["sql"]
    assert captured["params"] == (NODE, OWNER)


def test_children_and_tables_sql_requires_the_owner(monkeypatch):
    captured = _patch_connect(monkeypatch, "app.repositories.node_repository")
    assert fetch_children(NODE, user_id=OWNER) == []
    assert "d.user_id = %s" in captured["sql"]
    assert fetch_tables_under([NODE], user_id=OWNER) == []
    assert "d.user_id = %s" in captured["sql"]


def test_images_by_node_sql_requires_the_owner(monkeypatch):
    captured = _patch_connect(monkeypatch, "app.repositories.image_repository")
    assert fetch_images_by_node(NODE, OWNER) == []
    assert "d.user_id = %s" in captured["sql"]
    assert captured["params"][1] == OWNER


def test_expand_hit_drops_a_node_the_user_does_not_own(monkeypatch):
    monkeypatch.setattr("app.retrieve.fetch_node", lambda node_id, user_id=None: None)
    assert expand_hit(NODE, {"include_siblings": True, "include_children": True}, OWNER) is None


def test_expand_hit_forwards_the_owner_through_the_hierarchy(monkeypatch):
    seen: list[tuple[str, object]] = []
    parent_id = uuid4()
    node = {
        "id": NODE,
        "parent_id": None,
        "node_type": "section",
        "document_id": uuid4(),
        "heading": "Owned",
        "text": "owned text",
        "page": 1,
        "path": "1",
    }

    def fetch_node(node_id, user_id=None):
        seen.append(("node", user_id))
        return node if node_id == NODE else None

    def fetch_siblings(node, limit=8, user_id=None):
        seen.append(("siblings", user_id))
        return []

    def fetch_children(parent_id, limit=32, node_type=None, user_id=None):
        seen.append(("children", user_id))
        return []

    monkeypatch.setattr("app.retrieve.fetch_node", fetch_node)
    monkeypatch.setattr("app.retrieve.fetch_siblings", fetch_siblings)
    monkeypatch.setattr("app.retrieve.fetch_children", fetch_children)

    expanded = expand_hit(
        NODE,
        {"include_siblings": True, "include_children": True, "prefer_tables": False},
        OWNER,
    )

    assert expanded is not None
    assert expanded["heading"] == "Owned"
    assert seen == [("node", OWNER), ("siblings", OWNER), ("children", OWNER)]
    assert OTHER not in [user_id for _kind, user_id in seen]


def test_image_retrieval_asks_for_the_owner(monkeypatch):
    seen = {}

    def fetch_images_by_node(node_id, user_id=None):
        seen["user_id"] = user_id
        return []

    monkeypatch.setattr("app.retrieve.fetch_images_by_node", fetch_images_by_node)
    assert retrieve_images([NODE], [], OWNER) == []
    assert seen["user_id"] == OWNER
