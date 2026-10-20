from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import ensure_data_dirs
from app.repositories import init_schema
from app.ingest import ingest_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a PDF into structured RAG (no chunking).")
    parser.add_argument("pdf", type=Path, help="Path to a PDF file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"File not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit("Expected a .pdf file")

    ensure_data_dirs()
    init_schema()
    result = ingest_pdf(pdf_path)
    print(f"ingested document_id={result['document_id']}")
    print(f"counts={result['counts']}")


if __name__ == "__main__":
    main()
