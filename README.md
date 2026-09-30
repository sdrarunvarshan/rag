# Structure-Aware  RAG

PDF documents are parsed with **Docling** into a heading / table tree and indexed at **section, subsection, and table** granularity. There is no fixed-size token chunking.

At query time, **LangGraph** runs `retrieve → generate`. Retrieval is unchanged (query understanding → hybrid pgvector + BM25 → RRF → rerank → hierarchy → tables → context). Generation uses **LangChain** `ChatOpenAI` against the Hugging Face router (`HF_TOKEN`). The `/query` response `flow` field still exposes every stage.

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
PostgreSQL (source of truth) + pgvector vectors + BM25 index
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
pgvector + sentence-transformers  lexical (rank-bm25)
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
LangGraph retrieve → generate          app/langgraph_rag.py
       ↓
LangChain + Qwen                       app/llm.py (Hugging Face router, HF_TOKEN)
       ↓
Grounded Answer
```

### MCP Interface

The RAG pipeline is also exposed as an MCP server using FastMCP.

```
AI Client
   ↓
MCP Client
   ↓
FastMCP (stdio)
   ↓
RAG tools
   ├── query_document
   ├── retrieve_document_context
   ├── get_document
   ├── cache_health
   └── rag_health
   ↓
Existing RAG pipeline
   ↓
LangGraph → Retrieval → Qwen
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
| LangGraph | Orchestrates retrieve → generate | `app/langgraph_rag.py` |
| LangChain + Qwen | Grounded generation from structured context only | `app/llm.py` |

The web UI and API return a `flow` object with one entry per stage so you can inspect hits, fusion scores, expansions, and the final context.

## Features

- Structure-aware ingest (headings and tables, not sliding-window chunks)
- Query understanding (type, scope, concepts) drives expansion and BM25 query shaping
- PostgreSQL as the source of truth for document trees
- Hybrid search: dense (pgvector + sentence-transformers) + lexical (BM25), fused with RRF
- Hierarchical expansion: parent section, siblings, children, and dedicated table retrieval
- Context organizer packs labeled blocks under a character budget
- Query `flow` payload so each pipeline stage is visible in the API response
- Optional `document_id` filter
- Valkey / Redis cache for retrieval results
- LLM via Hugging Face router (`https://router.huggingface.co/v1`), default model **Qwen**, orchestrated with LangGraph and LangChain (`HF_TOKEN`)
- MCP interface using FastMCP
- MCP tools for querying, retrieval, document access, and health checks
- AI agent that uses MCP tools with LLM function calling for grounded answers
- **Temporal.io integration** for durable workflow execution with automatic retries and crash recovery

## Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI + Uvicorn |
| MCP | FastMCP |
| Parse | Docling |
| Store | PostgreSQL (`documents`, `nodes`) |
| Vectors | pgvector + sentence-transformers |
| Lexical | rank-bm25 |
| Cache | Valkey (Redis protocol) |
| LLM | Hugging Face Inference Router via LangChain ChatOpenAI (`HF_TOKEN`) |
| Orchestration | LangGraph (`retrieve` → `generate`) + Temporal (durable workflows) |
| Observability | OpenTelemetry + Arize Phoenix |
| Evaluation | RAGAS + DeepEval |

## Repository layout

```
app/
  main.py              FastAPI routes: /, /health, /documents, /ingest, /query
  my_server.py         FastMCP MCP server and RAG tools
  agent.py             AI agent that uses MCP tools with Qwen LLM
  test_agent.py        Test script for MCP server connectivity
  ingest.py            Docling PDF → structured nodes
  query_understand.py  Query type, scope, concepts, expansion plan
  db.py                Postgres schema and queries
  index.py             pgvector + BM25 index
  pgvector_search.py   pgvector-based vector search
  retrieve.py          Hybrid search, RRF, rerank, hierarchy, tables, context, flow
  langgraph_rag.py     LangGraph retrieve → generate
  llm.py               LangChain ChatOpenAI on Hugging Face router (Qwen)
  cache.py             Valkey
  config.py            Environment
  telemetry.py         OpenTelemetry instrumentation with Phoenix
  evaluation.py        RAGAS evaluation metrics
  temporal_activities.py Temporal activities for durable execution
  temporal_workflows.py Temporal workflows (IngestWorkflow, QueryWorkflow)
  temporal_worker.py   Temporal worker process
scripts/
  ingest_pdf.py        CLI ingest
  check_services.py    Postgres / Valkey ping
  start_phoenix.py     Start Phoenix observability server
tests/
  test_rag_evaluation.py  DeepEval pytest tests for CI/CD
.env.example       Copy to .env (never commit .env)
requirements.txt
```

## Prerequisites
- uv
- Python 3.10+
- PostgreSQL on `localhost:5432`
- Valkey or Redis on `127.0.0.1:6379`
- A [Hugging Face access token](https://huggingface.co/settings/tokens) (`HF_TOKEN`) for generation (retrieval still works without it)
- Temporal Server (optional, for durable workflow execution)

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

```

**Windows (PowerShell)**

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
copy .env.example .env
```

**Linux / macOS**

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
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
| `TEMPORAL_HOST` | Temporal server host (default `localhost`) |
| `TEMPORAL_PORT` | Temporal server port (default `7233`) |
| `TEMPORAL_NAMESPACE` | Temporal namespace (default `default`) |
| `TEMPORAL_TASK_QUEUE` | Temporal task queue (default `rag-task-queue`) |

`Qwen/Qwen3.5-0.9B` is available on the Hugging Face Inference Router. That checkpoint is for  local vLLM / SGLang server. 
```
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_MODEL=Qwen/Qwen3.5-0.9B
```

(Keep the RAG API on port 8000.)

## Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- UI: `http://127.0.0.1:8000/`
- Docs: `http://127.0.0.1:8000/docs`

Restart Uvicorn after changing `.env` (`--reload` does not always reload environment files).

## Temporal Setup (Optional)

Temporal provides durable workflow execution with automatic retries and crash recovery. The RAG API will automatically use Temporal if available, otherwise it falls back to direct execution.

### Install Temporal CLI

```bash
# macOS
brew install temporal

# Linux
curl -sSf https://temporal.io/cli.sh | sh

# Windows
# Download from https://temporal.io/cli
```

### Start Temporal Server

```bash
# Start a local Temporal server (single-node for development)
temporal server start-dev

# Or use Docker
docker run --rm -p 7233:7233 temporalio/server:latest
```

### Start Temporal Worker

In a separate terminal, start the Temporal worker to execute workflows:

```bash
uv run python -m app.temporal_worker
```

The worker will:
- Connect to Temporal at `localhost:7233`
- Listen on the `rag-task-queue`
- Execute ingest and query workflows

### Temporal Benefits

- **Crash Recovery**: If the FastAPI server crashes during ingest/query, Temporal automatically resumes the workflow from the last completed activity
- **Automatic Retries**: Failed activities are automatically retried with configurable policies
- **Visibility**: Monitor workflow execution in the Temporal web UI at `http://localhost:8233`
- **Durable Execution**: Workflows survive server restarts and network failures

### Without Temporal

If Temporal is not running, the API automatically falls back to direct execution. All functionality remains available, but without the durability guarantees provided by Temporal.

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Postgres and Valkey ping |
| `GET` | `/documents` | Indexed documents |
| `POST` | `/ingest` | Multipart PDF (`file`) |
| `POST` | `/query` | Question + optional `document_id` |

## MCP Server

The project exposes the Structure-Aware RAG pipeline through the Model Context Protocol (MCP) using FastMCP.

The MCP server provides an interface for MCP-compatible AI clients to interact with the RAG system without directly calling the FastAPI `/query` endpoint.

### MCP tools

| Tool | Description |
| --- | --- |
| `query_document` | Runs the complete RAG pipeline: retrieval → hierarchy → context → LangGraph → generation |
| `retrieve_document_context` | Runs retrieval only and returns query planning, retrieved sections, tables, and structured context |
| `get_document` | Retrieves metadata for a document using its `document_id` |
| `cache_health` | Checks Valkey availability |
| `rag_health` | Returns basic RAG service health information |

### MCP transport

The MCP server uses `stdio` transport. The client spawns the server as a subprocess and communicates via stdin/stdout.

### Start MCP server

```bash
uv run python -m app.my_server
```

### Ingest

```bash
curl -F "file=@./paper.pdf" http://127.0.0.1:8000/ingest
```

## AI Agent

The project includes an AI agent (`app/agent.py`) that connects to the MCP server and uses an LLM (Qwen via Hugging Face) to answer questions using the RAG tools.

The agent:
- Spawns the MCP server process using stdio transport
- Retrieves available MCP tools
- Converts MCP tools to OpenAI-compatible function calling format
- Uses Qwen (via Hugging Face router) to decide which tools to call
- Executes MCP tools and returns grounded answers

### Run AI Agent

Start the MCP server first:

```bash
uv run python -m app.my_server
```

In a separate terminal, run the AI agent:

```bash
uv run python -m app.agent
```

The agent will prompt for a question and use the MCP tools to answer it.

### Test MCP Connection

To verify MCP server connectivity and list available tools:

```bash
uv run python -m app.test_agent
```

This will output:
- Available MCP tools
- Tool descriptions

## Ingest

CLI:

```bash
uv run python scripts/ingest_pdf.py ./paper.pdf
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
- `flow` — stage-by-stage pipeline trace (understand → vector → bm25 → hybrid → rerank → hierarchy → tables → context → llm)
- `llm_skipped` — `true` if generation was skipped or failed

The model is instructed to answer **only from retrieved sections**. If the PDF never defines a term, the answer will say the context is insufficient instead of inventing a definition.

## Observability & Evaluation

### Arize Phoenix (OpenTelemetry Tracing)

The application includes OpenTelemetry instrumentation with Arize Phoenix for distributed tracing and observability.

**Start Phoenix server:**

```bash
uv run python scripts/start_phoenix.py
```

Phoenix UI will be available at `http://localhost:6006`.

**Configure Phoenix:**

Add to `.env`:

```bash
PHOENIX_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=rag-evaluation
```

Tracing is automatically enabled when the RAG API starts. Phoenix captures:
- FastAPI request traces
- LangChain LLM calls
- Retrieval pipeline stages
- Custom spans for query understanding and context organization

### RAGAS Evaluation

RAGAS provides comprehensive metrics for RAG system evaluation:

```python
from app.evaluation import RAGASEvaluator

evaluator = RAGASEvaluator()
results = evaluator.evaluate_dataset(
    questions=["question1", "question2"],
    answers=["answer1", "answer2"],
    contexts=[["context1"], ["context2"]],
    ground_truths=["truth1", "truth2"]
)
```

Available metrics:
- **Faithfulness**: Measures if answers are grounded in retrieved context
- **Answer Relevance**: Measures if answers address the user's question
- **Context Precision**: Measures if retrieved context is relevant
- **Context Recall**: Measures if all relevant information was retrieved

### DeepEval CI/CD Testing

DeepEval provides pytest-based tests for continuous quality assurance:

```bash
# Run evaluation tests
uv run pytest tests/test_rag_evaluation.py -v
```

Tests include:
- Faithfulness verification
- Answer relevancy checks
- Contextual relevancy validation
- Comprehensive pipeline quality tests

**CI/CD Integration:**

The `.github/workflows/ci.yml` file includes a GitHub Actions workflow that:
- Runs DeepEval tests on every push/PR
- Executes RAGAS evaluation (when HF_TOKEN is available)
- Ensures RAG quality gates before deployment

Set secrets in GitHub:
- `HF_TOKEN`: Hugging Face token for LLM access

## What is stored where

| Store | Role |
| --- | --- |
| PostgreSQL | Document metadata + full node text + vector embeddings |
| `data/bm25.pkl` | BM25 corpus (gitignored). Generated from PostgreSQL nodes. |
| Valkey | Cached retrieval JSON |

Deleting the source PDF on disk **does not** remove the document from Postgres. Query still works until you delete the `documents` row (`nodes` cascade via `ON DELETE CASCADE`) and rebuild indexes.

### Rebuilding BM25

Because `bm25.pkl` is a local derived artifact generated from PostgreSQL nodes, you should regenerate it whenever your PostgreSQL document corpus changes (e.g. after ingest or deletion):

```bash
uv run python scripts/rebuild_bm25.py
```


## License

Add a license file if you want others to reuse this project (for example MIT).
