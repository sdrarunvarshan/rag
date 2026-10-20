"""The BM25 fingerprint must change when text changes anywhere in a node."""

import pytest

from app.bm25.index import corpus_fingerprint

pytestmark = pytest.mark.unit

NODE_ID = "11111111-1111-1111-1111-111111111111"
DOCUMENT_ID = "22222222-2222-2222-2222-222222222222"


def test_fingerprint_changes_when_text_after_the_first_100_characters_changes():
    prefix = "Our company provides customer support and product assistance."
    prefix = prefix.ljust(100, ".")
    original = {
        "id": NODE_ID,
        "document_id": DOCUMENT_ID,
        "search_text": prefix + "The refund period is 7 days.",
    }
    edited = {
        "id": NODE_ID,
        "document_id": DOCUMENT_ID,
        "search_text": prefix + "The refund period is 30 days.",
    }

    assert original["search_text"][:100] == edited["search_text"][:100]
    assert corpus_fingerprint([original]) != corpus_fingerprint([edited])
