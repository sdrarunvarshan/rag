# Chunkless Structured RAG

PDF documents are parsed with **Docling** into a heading / table tree and indexed at **section, subsection, and table** granularity. There is no fixed-size token chunking.

Retrieval is hybrid (**txtai + USearch** vectors and **BM25**), fused with Reciprocal Rank Fusion, reranked, then expanded to the **full parent section** (including child tables). Answers are generated with **Qwen** through Hugging Face’s OpenAI-compatible Inference Router.

```
Documents
   ↓
Docling
   ↓
Structured Document Tree
   ↓
Sections / Subsections / Tables
   ↓
        txtai
   ┌───────────────┐
   │ Embeddings    │
   │ Vector Search │
   └───────────────┘
          ↓
     BM25 Search
          ↓
   Hybrid Retrieval (RRF)
          ↓
      Reranking
          ↓
   Retrieve Full Section
          ↓
    Context Building
          ↓
   LLM (Hugging Face / Qwen)
```

## Features

- Structure-aware ingest (headings and tables, not sliding-window chunks)
- PostgreSQL as the source of truth for document trees
- Hybrid search: dense (txtai / USearch) + lexical (BM25)
- Query `flow` payload so each pipeline stage is visible in the API response
- Optional `document_id` filter
- Valkey / Redis cache for retrieval results
- LLM via Hugging Face router (`https://router.huggingface.co/v1`)

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
  main.py          FastAPI routes: /, /health, /documents, /ingest, /query
  ingest.py        Docling PDF → structured nodes
  db.py            Postgres schema and queries
  index.py         txtai + BM25 index
  usearch_ann.py   USearch backend for txtai
  retrieve.py      Hybrid search, rerank, section expand, flow
  llm.py           Hugging Face OpenAI-compatible chat
  cache.py         Valkey
  config.py        Environment
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

- `answer` — LLM output (or a skip/error message)
- `sources` — expanded sections used as context
- `context` — text sent to the model
- `flow` — stage-by-stage pipeline trace
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
