# Chunkless Structured RAG

PDF documents are parsed with **Docling** into a heading / table tree and indexed at **section, subsection, and table** granularity. There is no fixed-size token chunking.

At query time, the pipeline runs **query understanding → hybrid retrieval → RRF fusion → reranking → hierarchical expansion → table retrieval → context organization → Qwen generation**. Every stage is implemented in this repo and exposed in the `/query` response `flow` field.

## Architecture

### Ingest (offline)

```
Documents
   ↓
Docling
   ↓
Structured Document Tree
   ↓
Sections / Subsections / Tables
   ↓
PostgreSQL (source of truth) + txtai/USearch vectors + BM25 index
```

### Query (online)

```
USER QUESTION
       ↓
Query Understanding                    app/query_understand.py
       ↓
Query Type + Scope + Concepts          definition | comparison | numeric | …
       ↓
┌──────────────┴──────────────┐
↓                             ↓
Dense Retrieval               BM25
txtai + USearch               lexical (rank-bm25)
app/index.py                  app/index.py
└──────────────┬──────────────┘
       ↓
RRF Fusion                             app/retrieve.py
       ↓
Reranker                               embedding similarity (+ table boost)
       ↓
Hierarchical Expansion
   ↙      ↓       ↘
Parent  Sibling  Children              app/retrieve.py (expand_hit)
       ↓
Table Retrieval                        app/retrieve.py (retrieve_tables)
       ↓
Context Organizer                      app/retrieve.py (organize_context)
       ↓
Structured Context                     labeled blocks within char budget
       ↓
Qwen                                   app/llm.py (Hugging Face router)
       ↓
Grounded Answer
```

| Stage | What it does | Code |
| --- | --- | --- |
| Query Understanding | Classifies query type, scope, concepts; sets expansion flags | `app/query_understand.py` |
| Dense + BM25 | Parallel vector and lexical search over indexed nodes | `app/index.py` |
| RRF Fusion | Reciprocal Rank Fusion merges rank lists | `app/retrieve.py` |
| Reranker | Re-scores fused candidates with embedding similarity | `app/retrieve.py` |
| Hierarchical Expansion | Walks hit → parent section; adds siblings and children per plan | `app/retrieve.py` |
| Table Retrieval | Pulls table nodes from hits and expanded sections | `app/retrieve.py` |
| Context Organizer | Orders blocks (parent / sibling / child / table) into structured context | `app/retrieve.py` |
| Qwen | Grounded generation from structured context only | `app/llm.py` |

The web UI and API return a `flow` object with one entry per stage so you can inspect hits, fusion scores, expansions, and the final context.

## Features

- Structure-aware ingest (headings and tables, not sliding-window chunks)
- Query understanding (type, scope, concepts) drives expansion and BM25 query shaping
- PostgreSQL as the source of truth for document trees
- Hybrid search: dense (txtai / USearch) + lexical (BM25), fused with RRF
- Hierarchical expansion: parent section, siblings, children, and dedicated table retrieval
- Context organizer packs labeled blocks under a character budget
- Query `flow` payload so each pipeline stage is visible in the API response
- Optional `document_id` filter
- Valkey / Redis cache for retrieval results
- LLM via Hugging Face router (`https://router.huggingface.co/v1`), default model **Qwen**

## Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI + Uvicorn |
| Parse | Docling |
| Store | PostgreSQL (`documents`, `nodes`) |
| Vectors | txtai embeddings + USearch ANN |
| Lexical | rank-bm25 |
| Cache | Valkey (Redis protocol) |
| LLM | Hugging Face Inference Router, OpenAI Python SDK |

## Repository layout

```
app/
  main.py              FastAPI routes: /, /health, /documents, /ingest, /query
  ingest.py            Docling PDF → structured nodes
  query_understand.py  Query type, scope, concepts, expansion plan
  db.py                Postgres schema and queries
  index.py             txtai + BM25 index
  usearch_ann.py       USearch backend for txtai
  retrieve.py          Hybrid search, RRF, rerank, hierarchy, tables, context, flow
  llm.py               Hugging Face OpenAI-compatible chat (Qwen)
  cache.py             Valkey
  config.py            Environment
scripts/
  ingest_pdf.py    CLI ingest
  check_services.py  Postgres / Valkey ping
.env.example       Copy to .env (never commit .env)
requirements.txt
```

## Prerequisites

- Python 3.10+
- PostgreSQL on `localhost:5432`
- Valkey or Redis on `127.0.0.1:6379`
- A [Hugging Face access token](https://huggingface.co/settings/tokens) (`HF_TOKEN`) for generation (retrieval still works without it)

### Database

```sql
CREATE DATABASE rag;
```

Tables `documents` and `nodes` are created on API startup.

Default URL (override in `.env`):

```
postgresql://postgres:1234@localhost:5432/rag
```

If that user is rejected, the app also tries `postgresql://1234:1234@localhost:5432/rag`.

### Valkey (optional but recommended)

Query results are cached when Valkey/Redis is reachable.

On WSL, bind so Windows can connect:

```bash
valkey-server --bind 0.0.0.0 --port 6379 --protected-mode no
```

Or set `VALKEY_URL` to the WSL IP from `wsl hostname -I`.

## Setup

```bash
git clone <your-repo-url>
cd rag
python -m venv .venv
```

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

**Linux / macOS**

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `HF_TOKEN`. Do not commit `.env`.

### Environment variables

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string |
| `VALKEY_URL` | Redis-compatible cache URL |
| `HF_TOKEN` | Hugging Face token (used as OpenAI-compatible `api_key`) |
| `OPENAI_BASE_URL` | Default `https://router.huggingface.co/v1` |
| `OPENAI_MODEL` | Default `Qwen/Qwen3.5-9B` (hosted on the HF router) |
| `LLM_MAX_TOKENS` | Generation cap (default `2048`) |
| `LLM_TEMPERATURE` | Default `0.7` |
| `LLM_TOP_P` | Default `0.8` |
| `LLM_PRESENCE_PENALTY` | Default `1.5` |
| `LLM_TOP_K` | Passed as `extra_body.top_k` (default `20`) |
| `EMBEDDING_MODEL` | Default `sentence-transformers/all-MiniLM-L6-v2` |
| `CACHE_TTL_SECONDS` | Default `3600` |

`Qwen/Qwen3.5-0.9B` is available on the Hugging Face Inference Router. That checkpoint is for  local vLLM / SGLang server. 
```
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_MODEL=Qwen/Qwen3.5-0.9B
```

(Keep the RAG API on port 8000.)

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- UI: `http://127.0.0.1:8000/`
- Docs: `http://127.0.0.1:8000/docs`

Restart Uvicorn after changing `.env` (`--reload` does not always reload environment files).

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Postgres and Valkey ping |
| `GET` | `/documents` | Indexed documents |
| `POST` | `/ingest` | Multipart PDF (`file`) |
| `POST` | `/query` | Question + optional `document_id` |

### Ingest

```bash
curl -F "file=@./paper.pdf" http://127.0.0.1:8000/ingest
```

CLI:

```bash
python scripts/ingest_pdf.py ./paper.pdf
```

The response includes `document_id`. The original PDF is parsed once; the file is not required afterward.

### Query

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What is the project title?\", \"document_id\": \"<uuid>\"}"
```

`document_id` is optional. Omit it to search the full corpus.

Response fields:

- `answer` — grounded LLM output (or a skip/error message)
- `query_plan` — query type, scope, concepts, and expansion flags from query understanding
- `sources` — expanded sections (parent / siblings / children) used as context
- `structured` — ordered context blocks with role labels (parent, sibling, child, table, hit)
- `context` — structured text sent to Qwen
- `flow` — stage-by-stage pipeline trace (understand → txtai → bm25 → hybrid → rerank → hierarchy → tables → context → llm)
- `llm_skipped` — `true` if generation was skipped or failed

The model is instructed to answer **only from retrieved sections**. If the PDF never defines a term, the answer will say the context is insufficient instead of inventing a definition.

## What is stored where

| Store | Role |
| --- | --- |
| PostgreSQL | Document metadata + full node text |
| `data/txtai` | Vector index (gitignored) |
| `data/bm25.pkl` | BM25 corpus (gitignored) |
| Valkey | Cached retrieval JSON |

Deleting the source PDF on disk **does not** remove the document from Postgres. Query still works until you delete the `documents` row (`nodes` cascade via `ON DELETE CASCADE`) and rebuild indexes.


## License

Add a license file if you want others to reuse this project (for example MIT).
