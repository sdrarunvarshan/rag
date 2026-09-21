#!/usr/bin/env python3
"""
Rebuild the local BM25 index (data/bm25.pkl) from nodes in PostgreSQL.
"""
import logging
import sys
from pathlib import Path

# Add project root to python path so we can import app modules
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from app.index import hybrid_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("rebuild_bm25")


def main():
    log.info("Starting BM25 rebuild from PostgreSQL...")
    hybrid_index.rebuild_bm25()
    log.info("Finished rebuilding BM25 index.")


if __name__ == "__main__":
    main()
