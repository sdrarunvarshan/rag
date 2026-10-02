from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.db import insert_document, insert_image, insert_nodes, node_counts, tree_preview
from app.garage_client import ensure_bucket, upload_image
from app.index import hybrid_index

log = logging.getLogger(__name__)


@dataclass
class ParsedNode:
    id: UUID
    parent_id: UUID | None
    node_type: str
    heading: str
    text: str = ""
    page: int | None = None
    path: str = ""
    table_count: int = field(default=0, repr=False)

    def search_text(self) -> str:
        parts = [self.heading or "", self.text or ""]
        return "\n".join(part for part in parts if part).strip()

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "node_type": self.node_type,
            "heading": self.heading,
            "text": self.text,
            "page": self.page,
            "path": self.path,
            "search_text": self.search_text(),
        }


@dataclass
class ParsedImage:
    id: UUID
    document_id: UUID
    node_id: UUID | None
    image_data: bytes
    mime_type: str
    page: int | None = None
    caption: str = ""


def _label(item: Any) -> str:
    label = getattr(item, "label", None)
    if label is None:
        return type(item).__name__.lower()
    value = getattr(label, "value", None) or str(label)
    return str(value).lower().replace("docitemlabel.", "")


def _page(item: Any) -> int | None:
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None
    first = prov[0]
    page = getattr(first, "page_no", None)
    if page is None:
        page = getattr(first, "page", None)
    return int(page) if page is not None else None


def _text(item: Any) -> str:
    text = getattr(item, "text", None)
    return text.strip() if isinstance(text, str) else ""


def _heading_level(item: Any) -> int:
    level = getattr(item, "level", None)
    if level:
        return max(1, int(level))
    if _label(item) in {"title", "document_index"}:
        return 1
    return 2


def _classify(item: Any) -> str:
    label = _label(item)
    name = type(item).__name__.lower()
    blob = f"{label} {name}"
    if any(token in blob for token in ("page_header", "page_footer", "key_value")):
        return "skip"
    if "table" in blob:
        return "table"
    if any(token in blob for token in ("picture", "image")):
        return "image"
    if any(token in blob for token in ("section_header", "title", "sectionheader")):
        return "heading"
    if _text(item):
        return "text"
    return "skip"


def _export_table(item: Any, doc: Any) -> str:
    try:
        md = item.export_to_markdown(doc=doc)
        if md and md.strip():
            return md.strip()
    except TypeError:
        try:
            md = item.export_to_markdown(doc)
            if md and md.strip():
                return md.strip()
        except Exception:
            pass
    except Exception:
        pass
    try:
        frame = item.export_to_dataframe()
        return frame.to_markdown(index=False)
    except Exception:
        return _text(item)


def _extract_image(item: Any, doc: Any) -> tuple[bytes, str] | None:
    """Docling's PictureItem.get_image returns a PIL image, or None unless
    generate_picture_images was enabled for the conversion."""
    try:
        image = item.get_image(doc)
    except TypeError:
        image = item.get_image(doc=doc)
    except Exception as exc:
        log.warning("Docling picture extraction failed: %s", exc)
        return None
    if image is None:
        return None
    pil = image
    nested = getattr(getattr(image, "image", None), "pil", None)
    if nested is not None:
        pil = nested
    if not hasattr(pil, "save"):
        return None
    buffer = BytesIO()
    pil.save(buffer, format="PNG")
    return buffer.getvalue(), "image/png"


_converter = None
_hash_patched = False


def _patch_docling_options_hash() -> None:
    """Docling hashes pipeline options with serialize_as_any=True; some Pydantic
    versions then raise Circular reference detected and ingest never starts."""
    global _hash_patched
    if _hash_patched:
        return

    def _safe_hash(pipeline_options: Any) -> str:
        name = type(pipeline_options).__qualname__
        payload = name
        try:
            payload = name + pipeline_options.model_dump_json(serialize_as_any=True)
        except Exception:
            try:
                payload = name + pipeline_options.model_dump_json()
            except Exception:
                payload = name + repr(pipeline_options)
        return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()

    try:
        from docling.utils import pipeline_cache
        from docling import document_converter as converter_mod

        pipeline_cache.create_pipeline_options_hash = _safe_hash
        converter_mod.create_pipeline_options_hash = _safe_hash
    except Exception as exc:
        log.warning("Could not patch Docling pipeline hash: %s", exc)
    _hash_patched = True


def _document_converter():
    global _converter
    _patch_docling_options_hash()
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = False
        options.generate_picture_images = True
        _converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            }
        )
    return _converter


def parse_pdf(path: Path) -> tuple[list[ParsedNode], list[ParsedImage]]:
    converter = _document_converter()
    result = converter.convert(str(path))

    document = result.document

    nodes: list[ParsedNode] = []
    images: list[ParsedImage] = []
    stack: list[tuple[int, ParsedNode]] = []
    counters: dict[int, int] = {}

    def next_path(level: int) -> str:
        for key in [key for key in counters if key > level]:
            del counters[key]
        counters[level] = counters.get(level, 0) + 1
        return ".".join(str(counters.get(lv, 1)) for lv in range(1, level + 1))

    def ensure_root() -> ParsedNode:
        if stack:
            return stack[-1][1]
        root = ParsedNode(
            id=uuid4(),
            parent_id=None,
            node_type="section",
            heading="Document",
            path="1",
            page=1,
        )
        counters[1] = 1
        nodes.append(root)
        stack.append((1, root))
        return root

    for item, _depth in document.iterate_items():
        kind = _classify(item)
        if kind == "skip":
            continue
        if kind == "heading":
            level = _heading_level(item)
            heading = _text(item) or "Untitled"
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            node_type = "section" if (level <= 1 or parent is None) else "subsection"
            node = ParsedNode(
                id=uuid4(),
                parent_id=parent.id if parent else None,
                node_type=node_type,
                heading=heading,
                page=_page(item),
                path=next_path(level),
            )
            nodes.append(node)
            stack.append((level, node))
            continue
        if kind == "table":
            parent = ensure_root()
            parent.table_count += 1
            table_text = _export_table(item, document)
            caption = _text(item)
            heading = caption or f"Table {parent.path}.{parent.table_count}"
            nodes.append(
                ParsedNode(
                    id=uuid4(),
                    parent_id=parent.id,
                    node_type="table",
                    heading=heading,
                    text=table_text,
                    page=_page(item),
                    path=f"{parent.path}.t{parent.table_count}",
                )
            )
            continue
        if kind == "image":
            current = ensure_root()
            image_data = _extract_image(item, document)
            if image_data:
                image_bytes, mime_type = image_data
                caption = _text(item)
                images.append(
                    ParsedImage(
                        id=uuid4(),
                        document_id=None,
                        node_id=current.id,
                        image_data=image_bytes,
                        mime_type=mime_type,
                        page=_page(item),
                        caption=caption,
                    )
                )
            continue
        if kind == "text":
            current = ensure_root()
            piece = _text(item)
            if not piece:
                continue
            current.text = f"{current.text}\n{piece}".strip() if current.text else piece
            if current.page is None:
                current.page = _page(item)

    if not nodes:
        ensure_root()
    return nodes, images


def ingest_pdf(path: Path, filename: str | None = None) -> dict[str, Any]:
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    display_name = filename or pdf_path.name
    log.info("Parsing PDF with Docling: %s", pdf_path)
    parsed, images = parse_pdf(pdf_path)
    if images:
        ensure_bucket()
    document_id = uuid4()
    insert_document(document_id, display_name)
    insert_nodes(document_id, [node.as_row() for node in parsed])

    images_stored = 0
    for img in images:
        img.document_id = document_id
        minio_key = upload_image(document_id, img.image_data, img.mime_type, img.id)
        insert_image(
            image_id=img.id,
            document_id=document_id,
            node_id=img.node_id,
            minio_key=minio_key,
            page=img.page,
            caption=img.caption,
            mime_type=img.mime_type,
        )
        images_stored += 1

    hybrid_index.rebuild()
    counts = node_counts(document_id)
    preview = tree_preview(document_id)
    log.info("Ingested %s as %s (%s nodes, %s images)", display_name, document_id, len(parsed), images_stored)
    return {
        "document_id": str(document_id),
        "filename": display_name,
        "counts": counts,
        "tree_preview": preview,
        "nodes_parsed": len(parsed),
        "images_stored": images_stored,
        "flow": ingest_flow(display_name, counts, preview, len(parsed), images_stored),
    }


def ingest_flow(
    filename: str,
    counts: dict[str, int],
    preview: list[dict[str, Any]],
    nodes_parsed: int,
    images_stored: int = 0,
) -> dict[str, dict[str, Any]]:
    tree_lines = [
        f"{item.get('path') or '-'} [{item['node_type']}] {item.get('heading') or ''}"
        for item in preview[:40]
    ]
    stages = [
        {
            "key": "documents",
            "title": "Documents",
            "summary": filename,
            "data": {"filename": filename},
        },
        {
            "key": "docling",
            "title": "Docling",
            "summary": f"Parsed structured tree ({nodes_parsed} nodes, {images_stored} images). No token chunks.",
            "data": {"parser": "DocumentConverter", "nodes": nodes_parsed, "images": images_stored},
        },
        {
            "key": "tree",
            "title": "Structured Document Tree",
            "summary": f"Showing {min(len(preview), 40)} of {counts.get('total', 0)} nodes",
            "data": {"preview": tree_lines, "total": counts.get("total", 0)},
        },
        {
            "key": "structure",
            "title": "Sections / Subsections / Tables",
            "summary": (
                f"{counts.get('section', 0)} sections, "
                f"{counts.get('subsection', 0)} subsections, "
                f"{counts.get('table', 0)} tables"
            ),
            "data": counts,
        },
        {
            "key": "images",
            "title": "Extracted Images",
            "summary": f"{images_stored} images extracted and stored in MinIO",
            "data": {"images": images_stored, "storage": "MinIO"},
        },
        {
            "key": "understand",
            "title": "Query Understanding",
            "summary": "Runs on query (type, scope, concepts).",
            "data": None,
        },
        {
            "key": "vector",
            "title": "pgvector + Sentence-Transformers",
            "summary": f"Indexed {counts.get('total', 0)} nodes (pgvector). Vector search runs on query.",
            "data": {"indexed": counts.get("total", 0), "backend": "pgvector"},
        },
        {
            "key": "bm25",
            "title": "BM25 Search",
            "summary": f"BM25 corpus rebuilt ({counts.get('total', 0)} docs). Search runs on query.",
            "data": {"indexed": counts.get("total", 0)},
        },
        {
            "key": "hybrid",
            "title": "Hybrid Retrieval",
            "summary": "Runs on query (Reciprocal Rank Fusion).",
            "data": None,
        },
        {
            "key": "rerank",
            "title": "Reranking",
            "summary": "Runs on query (txtai similarity).",
            "data": None,
        },
        {
            "key": "hierarchy",
            "title": "Hierarchical Expansion",
            "summary": "Runs on query (parent, sibling, children).",
            "data": None,
        },
        {
            "key": "tables",
            "title": "Table Retrieval",
            "summary": "Runs on query (tables under expanded parents).",
            "data": None,
        },
        {
            "key": "context",
            "title": "Context Organizer",
            "summary": "Runs on query (structured blocks for Qwen).",
            "data": None,
        },
        {
            "key": "graph",
            "title": "LangGraph",
            "summary": "Runs on query (retrieve → generate).",
            "data": None,
        },
        {
            "key": "llm",
            "title": "LangChain + Qwen",
            "summary": "Runs on query (grounded answer via Hugging Face).",
            "data": None,
        },
    ]
    return {stage["key"]: stage for stage in stages}
