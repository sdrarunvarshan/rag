# Structure-Aware RAG

**Structure-aware Retrieval-Augmented Generation** for PDF documents. Documents are parsed with [Docling](https://github.com/DS4SD/docling) into a heading / table tree and indexed at section, subsection, and table granularity — no fixed-size token chunking.

At query time, [LangGraph](https://github.com/langchain-ai/langgraph) runs **retrieve → generate**. Retrieval is hybrid (pgvector + BM25 → RRF → rerank → hierarchy → tables → context). Generation uses LangChain `ChatOpenAI` against the Hugging Face router (`HF_TOKEN`). The `/query` response `flow` field exposes every pipeline stage.

---

## Architecture

### Ingest (offline)

```
USER UPLOADS PDF
        │
        ▼
     Docling
        │
   ┌────┴────┐
   ▼         ▼
Text/Tables  Extracted Images
   │              │
   ▼              ▼
PostgreSQL     Garage (S3)
+ pgvector     + PostgreSQL
+ metadata     (image refs)
```

**Text / Tables path**

```
Documents → Docling → Structured Document Tree
  → Sections / Subsections / Tables
  → PostgreSQL (source of truth) + pgvector vectors + BM25 index
```

**Images path**

```
Documents → Docling → Extracted Images
  → Garage (S3-compatible storage) + PostgreSQL (image metadata references)
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
app/index.py                   app/index.py
└──────────────┬──────────────┘
       ↓
RRF Fusion                             app/retrieve.py
       ↓
Reranker                               embedding similarity (+ table boost)
       ↓
Hierarchical Expansion
   ↙     ↓       ↘
Parent  Sibling  Children              app/retrieve.py (expand_hit)
       ↓
Table Retrieval                        app/retrieve.py (retrieve_tables)
       ↓
Associated Image Retrieval             app/retrieve.py (retrieve_images)
       ↓
Context Organizer                      app/retrieve.py (organize_context)
       ↓
Structured Context                    labeled blocks within char budget
       ↓
LangGraph retrieve → generate          app/langgraph_rag.py
       ↓
LangChain + Qwen                       app/llm.py (Hugging Face router, HF_TOKEN)
       ↓
Answer + Relevant Images
```

### MCP Interface

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
   ├── get_document_images
   ├── cache_health
   └── rag_health
   ↓
Existing RAG pipeline
   ↓
LangGraph → Retrieval → Qwen
```

### Pipeline stages

| Stage | What it does | Code |
|-------|--------------|------|
| Query Understanding | Classifies query type, scope, concepts; sets expansion flags | `app/query_understand.py` |
| Dense + BM25 | Parallel vector and lexical search over indexed nodes | `app/index.py` |
| RRF Fusion | Reciprocal Rank Fusion merges rank lists | `app/retrieve.py` |
| Reranker | Re-scores fused candidates with embedding similarity | `app/retrieve.py` |
| Hierarchical Expansion | Walks hit → parent section; adds siblings and children per plan | `app/retrieve.py` |
| Table Retrieval | Pulls table nodes from hits and expanded sections | `app/retrieve.py` |
| Associated Images | Pulls images linked to top hits and expanded sections | `app/retrieve.py` |
| Context Organizer | Orders blocks (parent / sibling / child / table) into structured context | `app/retrieve.py` |
| LangGraph | Orchestrates retrieve → generate | `app/langgraph_rag.py` |
| LangChain + Qwen | Grounded generation from structured context only | `app/llm.py` |

The web UI and API return a `flow` object with one entry per stage so you can inspect hits, fusion scores, expansions, associated images, and the final context.

---

## Features

- **Structure-aware ingest** — headings and tables, not sliding-window chunks
- **User Authentication** — JWT-based authentication securely protects the application's core endpoints
-**Document deletion** — Removes document records and related data, cleans up associated Garage objects, invalidates the user's retrieval cache, and rebuilds the BM25 index as appropriate. Storage cleanup failures are handled as partial failures and may require reconciliation.
- **Image extraction and storage** — Docling extracts images; Garage stores them via a robust `boto3` client; PostgreSQL holds metadata references
- **Query understanding** — type, scope, and concepts drive expansion and BM25 query shaping
- **PostgreSQL as source of truth** for document trees and image metadata
- **Hybrid search** — dense (pgvector + sentence-transformers) + lexical (BM25), fused with RRF
- **Hierarchical expansion** — parent section, siblings, children, and dedicated table retrieval
- **Associated image retrieval** — automatically resolves and returns images linked to top hits and expanded sections alongside the answer
- **Context organizer** — packs labeled blocks under a character budget
- **Query flow payload** — every pipeline stage is visible in the API response
- **Optional `document_id` filter**
- **Valkey / Redis cache** for retrieval results
- **LLM via Hugging Face router** (`https://router.huggingface.co/v1`), default model Qwen, orchestrated with LangGraph and LangChain (`HF_TOKEN`)
- **MCP interface** using FastMCP
- **MCP tools** for querying, retrieval, document access, and health checks
- **AI agent** that uses MCP tools with LLM function calling for grounded answers
- **Temporal.io** integration for durable workflow execution with automatic retries and crash recovery

---

## Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI + Uvicorn |
| MCP | FastMCP |
| Parse | Docling |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Store | PostgreSQL (documents, nodes, images) |
| Image Storage | Garage (S3-compatible) |
| Vectors | pgvector + sentence-transformers |
| Lexical | rank-bm25 |
| Cache | Valkey (Redis protocol) |
| LLM | Hugging Face Inference Router via LangChain ChatOpenAI (`HF_TOKEN`) |
| Orchestration | LangGraph (retrieve → generate) + Temporal (durable workflows) |
| Observability | OpenTelemetry + Arize Phoenix |
| Evaluation | RAGAS + DeepEval |

---

## Repository layout

```
app/
  main.py                 FastAPI routes: /, /health, /documents, /ingest, /query
  my_server.py            FastMCP server with user-aware and legacy tool sets
  agent.py                Qwen tool-calling agent with optional user-aware MCP client
  test_agent.py           Test script for MCP server connectivity
  ingest.py               Docling PDF → structured nodes + images
  query_understand.py     Query type, scope, concepts, expansion plan
  db.py                   Postgres schema and queries (documents, nodes, images)
  models.py               SQLAlchemy ORM models
  index.py                pgvector + BM25 index
  pgvector_search.py      pgvector-based vector search
  retrieve.py             Hybrid search, RRF, rerank, hierarchy, tables, context, flow
  langgraph_rag.py        LangGraph retrieve → generate
  llm.py                  LangChain ChatOpenAI on Hugging Face router (Qwen)
  cache.py                Valkey
  config.py               Environment
  garage_client.py        Garage (S3-compatible) client for image storage
  telemetry.py            OpenTelemetry instrumentation with Phoenix
  evaluation.py           RAGAS evaluation metrics
  temporal_activities.py  Temporal activities for durable execution
  temporal_workflows.py   Temporal workflows (IngestWorkflow, QueryWorkflow)
  temporal_worker.py      Temporal worker process

alembic/
  env.py                  Alembic environment configuration
  script.py.mako          Migration script template
  versions/               Database migration files

scripts/
  ingest_pdf.py           CLI ingest
  check_services.py       Postgres / Valkey / Garage ping
  start_phoenix.py        Start Phoenix observability server

tests/
  test_rag_evaluation.py  DeepEval pytest tests for CI/CD

.env.example              Copy to .env (never commit .env)
requirements.txt
alembic.ini               Alembic configuration
```

---

## Prerequisites

- [uv](https://github.com/astral-sh/uv)
- Python 3.12+
- PostgreSQL on `localhost:5432`
- Valkey or Redis on `127.0.0.1:6379` (optional but recommended)
- Docker (for Garage storage)
- A Hugging Face access token (`HF_TOKEN`) for generation (retrieval still works without it)
- Temporal Server (optional, for durable workflow execution)

### Database (PostgreSQL + pgvector)

PostgreSQL is the source of truth for document metadata, structured nodes, vector embeddings, and image metadata. The `pgvector` extension supports dense vector retrieval.

This project uses Docker Compose to run PostgreSQL.

**1. Start PostgreSQL**

From the project root:

```bash
docker compose up -d postgres
```

**2. Verify the database is ready**

```bash
docker compose ps
docker exec postgres pg_isready -U postgres -d rag
```

Wait until PostgreSQL reports that it is accepting connections.

**3. Configure the database URL**

Set `DATABASE_URL` in your `.env` file:

```env
DATABASE_URL=postgresql://postgres:1234@localhost:5432/rag
```

Use `localhost` when running the backend directly on your host machine. If the backend runs inside Docker Compose, use `postgres` as the hostname.

**4. Apply database migrations**

After installing project dependencies and configuring `.env`, run:

```bash
uv run alembic upgrade head
```

Alembic creates and updates the database schema using the migration files in `alembic/versions/`.

**Additional migration commands**

Create a migration after changing SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "Describe schema change"
```

Roll back one migration:

```bash
uv run alembic downgrade -1
```

**Note:** The Compose configuration initializes the `rag` database automatically on the first start. You do not need to execute `CREATE DATABASE rag;` manually. Database data persists in the `postgres_data` Docker volume.

Default URL (override in `.env`):

```
postgresql://postgres:1234@localhost:5432/rag
```


### Garage Configuration

This project uses Garage for S3-compatible object storage.

Before starting Garage, configure "garage/garage.toml" with your own "rpc_secret", "admin_token", and "metrics_token". 

Generate a unique RPC secret on Windows using PowerShell:

```
uv run python -c "import secrets; print(secrets.token_hex(32))"
```


### Garage (S3-compatible storage)

Garage stores extracted images from PDFs.

Default configuration (override in `.env`):

```
GARAGE_ENDPOINT=http://localhost:3900
GARAGE_ACCESS_KEY=<generated-access-key>
GARAGE_SECRET_KEY=<generated-secret-key>
GARAGE_SECURE=false
GARAGE_BUCKET=rag-documents
GARAGE_REGION=garage
```

**Start Garage with Docker Compose:**

```bash
docker compose up -d garage
```
**Initialize Garage:**

```bash
# Check the Garage node
docker exec garage /garage status

# Assign layout (use the NODE_ID from status)
docker exec garage /garage layout assign <NODE_ID> -z dc1 -c 1G
docker exec garage /garage layout show

# Apply the pending layout version
docker exec garage /garage layout apply --version <PENDING_VERSION>

# Create access key
docker exec garage /garage key create rag-app
docker exec garage /garage key list

# Create bucket
docker exec garage /garage bucket create rag-documents

# Allow the key to access the bucket
docker exec garage /garage bucket allow --read --write --owner rag-documents --key rag-app

# Verify
docker exec garage /garage bucket info rag-documents
```

Garage endpoints:

- S3 API: `http://localhost:3900`
- Web UI: `http://localhost:3902`

### Valkey (optional but recommended)

Query results are cached when Valkey/Redis is reachable.

On WSL, bind so Windows can connect:

```bash
valkey-server --bind 0.0.0.0 --port 6379 --protected-mode no
```

Or set `VALKEY_URL` to the WSL IP from `wsl hostname -I`.

---

## Setup

```bash
git clone <your-repo-url>
cd rag
```
### Application setup

**Windows (PowerShell)**

```powershell
uv venv
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

Edit `.env` and set `HF_TOKEN`. **Do not commit `.env`.**

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | Secret key for JWT token generation |
| `JWT_ALGORITHM` | JWT signing algorithm (default `HS256`) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration duration (default `60`) |
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
| `MCP_USER_ID` | Optional user UUID used by `app.my_server` when starting in user-aware  mode. If unset, the server uses legacy single-user mode. |
| `CACHE_TTL_SECONDS` | Default `3600` |
| `TEMPORAL_HOST` | Temporal server host (default `localhost`) |
| `TEMPORAL_PORT` | Temporal server port (default `7233`) |
| `TEMPORAL_NAMESPACE` | Temporal namespace (default `default`) |
| `TEMPORAL_TASK_QUEUE` | Temporal task queue (default `rag-task-queue`) |
| `GARAGE_ENDPOINT` | Garage server endpoint (default `http://localhost:3900`) |
| `GARAGE_ACCESS_KEY` | Garage access key |
| `GARAGE_SECRET_KEY` | Garage secret key |
| `GARAGE_SECURE` | Use HTTPS for Garage (default `false`) |
| `GARAGE_BUCKET` | Garage bucket name (default `rag-documents`) |
| `GARAGE_REGION` | Garage region (default `garage`) |

### Local Qwen (optional)

`Qwen/Qwen3.5-0.9B` is available on the Hugging Face Inference Router. For a local vLLM / SGLang server:

```
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_MODEL=Qwen/Qwen3.5-0.9B
```

(Keep the RAG API on port `8000`.)

---

## Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **UI:** http://127.0.0.1:8000/
- **Docs:** http://127.0.0.1:8000/docs

Restart Uvicorn after changing `.env` (`--reload` does not always reload environment files).

## Running Locally

### 1. Start Infrastructure

Start the required infrastructure services, including PostgreSQL, Garage, and Temporal, as configured in `docker-compose.yml`.

```bash
docker compose up -d
```

Verify that the services are running:

```bash
docker compose ps
```

Ensure all required services are healthy before proceeding.

### 2. Start the Temporal Worker

Open a new terminal in the project directory and start the Temporal worker:

```bash
uv run python -m app.temporal_worker
```

Keep this terminal running while using the application. The worker polls the `rag-task-queue` task queue and executes registered Temporal workflows and activities.

### 3. Start the FastAPI Application

Open another terminal in the project directory and start the API server:

```bash
uv run uvicorn app.main:app --reload
```

Once the server starts, access the application at:

- **API:** http://localhost:8000
- **Interactive API documentation:** http://localhost:8000/docs
- **Temporal Web UI:** http://localhost:8233

### 4. Monitor Temporal Workflows

Open the [Temporal Web UI](http://localhost:8233) to inspect workflow executions, execution status, and activity progress.

If document ingestion does not complete, check the Temporal workflow status and the worker logs for pending activities, connection failures, or execution errors.

### Important Notes

- Keep the infrastructure services, Temporal worker, and FastAPI server running while using the application.
- Ensure the API and worker use the same Temporal server address and task queue.
- When both Python processes run directly on the host, the default Temporal address is `localhost:7233`.
- If a service fails to start, inspect its logs using:

  ```bash
  docker compose logs -f <service_name>
  ```

- If Temporal workflows remain pending, verify that the worker is connected to the Temporal server and polling `rag-task-queue`.

### Benefits

- **Crash recovery** — if the FastAPI server crashes mid-ingest/query, Temporal resumes from the last completed activity
- **Automatic retries** — failed activities are retried with configurable policies
- **Visibility** — monitor workflows in the Temporal web UI at http://localhost:8233
- **Durable execution** — workflows survive server restarts and network failures

Without Temporal, the API falls back to direct execution. All functionality remains available, without the durability guarantees.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/register` | Register a new user |
| `POST` | `/auth/login` | Login and receive a JWT access token |
| `GET` | `/auth/me` | Get current authenticated user details (Protected) |
| `GET` | `/health` | Service health and dependency status, including optional-service   availability |
| `GET` | `/documents` | Indexed documents (Protected, requires Bearer token) |
| `DELETE` | `/documents/{document_id}` | Complete deletion from Postgres and Garage (Protected) |
| `GET` | `/documents/{document_id}/images` | Get images for a document (Protected) |
| `GET` | `/images/{image_id}` | Serve an image after validating document ownership (Protected) |
| `POST` | `/ingest` | Multipart PDF (`file`) (Protected) |
| `POST` | `/query` | Question + optional `document_id` (complete response, Protected) |
| `POST` | `/query/stream` | Question + optional `document_id` (SSE stream: retrieved → tokens → done, Protected) |

### Ingest

```bash
curl -F "file=@./paper.pdf" http://127.0.0.1:8000/ingest
```

CLI alternative:

```bash
uv run python scripts/ingest_pdf.py ./paper.pdf
```

The response includes `document_id`. The original PDF is parsed once; the file is not required afterward.

### Query

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the project title?", "document_id": "<uuid>"}'
```

`document_id` is optional. Omit it to search the full corpus.

**Response fields:**

| Field | Description |
|-------|-------------|
| `answer` | Grounded LLM output (or a skip/error message) |
| `query_plan` | Query type, scope, concepts, and expansion flags |
| `sources` | Expanded sections (parent / siblings / children) used as context |
| `images` | Images associated with retrieved sections (`id`, `minio_key`, `caption`, `page`, `url`) |
| `structured` | Ordered context blocks with role labels (`parent`, `sibling`, `child`, `table`, `hit`) |
| `context` | Structured text sent to Qwen |
| `flow` | Stage-by-stage pipeline trace (`understand` → `vector` → `bm25` → `hybrid` → `rerank` → `hierarchy` → `tables` → `images` → `context` → `llm`) |
| `llm_skipped` | `true` if generation was skipped or failed |

The model is instructed to answer **only from retrieved sections**. If the PDF never defines a term, the answer will say the context is insufficient instead of inventing a definition.

---

## MCP server

The project exposes the Structure-Aware RAG pipeline through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) using FastMCP.

### MCP tools

| Tool | Description |
|------|-------------|
| `query_document` | Full RAG pipeline: retrieval → hierarchy → context → LangGraph → generation |
| `retrieve_document_context` | Retrieval only: query planning, sections, tables, structured context |
| `get_document` | Document metadata by `document_id` |
| `get_document_images` | Images extracted from a document (Garage references) |
| `cache_health` | Valkey and Garage availability |
| `rag_health` | Basic RAG service health |

### Transport and tenant isolation

The MCP interface uses FastMCP with local stdio transport. The AI agent launches the MCP server as a subprocess.

The server supports two operating modes:

- **User-aware mode:** `create_rag_mcp_server(user_id)` creates an MCP server whose document tools receive a server-side user context. The server can obtain the user ID from the `MCP_USER_ID` environment variable when launched directly.
- **Legacy single-user mode:** `create_legacy_mcp_server()` exposes legacy tools without a user-specific tenant context. Use this only for trusted, single-user local development.

In user-aware mode, the document tools pass the injected user ID to the existing RAG pipeline and document database functions. This is intended to enforce tenant-scoped access, provided the underlying retrieval and database functions correctly apply the user filter.

**Security considerations:**

- Authenticate users at the application or trusted gateway boundary.
- Derive the user ID from the authenticated session or verified JWT, not from an untrusted LLM tool argument.
- Do not expose legacy single-user tools to untrusted or multi-user clients.
- Stdio is a local process transport, not an authentication mechanism.
- Verify that FastMCP excludes the injected `user_id` parameter from the LLM-facing tool schema before relying on the claim that the model cannot supply it.

Run the MCP server locally:

```bash
uv run python -m app.my_server
```

For user-aware mode, set `MCP_USER_ID` to a valid user UUID in the environment before launching the server.

```

### AI agent

`app/agent.py` implements an AI agent that connects to the FastMCP server and uses Qwen through the Hugging Face Inference Router for tool calling.

The agent:

1. Connects to the MCP server using `FastMCP Client` and `StdioTransport`.
2. Discovers available MCP tools and their input schemas.
3. Converts MCP tool definitions into OpenAI-compatible function tools.
4. Sends the user's question to Qwen with automatic tool selection.
5. Executes the requested MCP tools and returns their results to the model.
6. Produces a final natural-language response.

#### User-aware execution

The agent exposes:

```python
async def ask(
    question: str,
    user_id: str | UUID | None = None,
):
    ...
```

When `user_id` is provided, `create_mcp_client_with_user()` creates a dedicated MCP client whose subprocess receives the `MCP_USER_ID` environment variable.

When `user_id` is omitted, the agent uses the legacy single-user client.

**Important:** The caller must obtain `user_id` from a trusted authentication context. The command-line argument and environment variable are not authentication mechanisms by themselves.

#### Run the agent

Start the agent from the project root:

```bash
uv run python -m app.agent
```

Enter a question when prompted. To use user-aware mode, pass a valid user UUID as the first command-line argument:

```bash
uv run python -m app.agent <USER_UUID>
```

The command-line argument is suitable for local testing. In a deployed application, pass the authenticated user's ID from the backend rather than accepting an arbitrary user ID from a client.

#### Test MCP connectivity

```bash
uv run python -m app.test_agent
```

This script can be used to inspect MCP connectivity and available tools.

---

## Observability & evaluation

### Arize Phoenix (OpenTelemetry tracing)

```bash
uv run python scripts/start_phoenix.py
```

Phoenix UI: http://localhost:6006

Add to `.env`:

```
PHOENIX_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=rag-evaluation
```

Tracing is enabled automatically when the RAG API starts. Phoenix captures:

- FastAPI request traces
- LangChain LLM calls
- Retrieval pipeline stages
- Custom spans for query understanding and context organization

### RAGAS evaluation

```python
from app.evaluation import RAGASEvaluator

evaluator = RAGASEvaluator()

results = evaluator.evaluate_dataset(
    questions=["question1", "question2"],
    answers=["answer1", "answer2"],
    contexts=[["context1"], ["context2"]],
    ground_truths=["truth1", "truth2"],
)
```

**Metrics:**

- **Faithfulness** — answers grounded in retrieved context
- **Answer Relevance** — answers address the user's question
- **Context Precision** — retrieved context is relevant
- **Context Recall** — all relevant information was retrieved

### Request correlation and error handling

The API uses request IDs to correlate HTTP responses with application logs. Request IDs are included in response headers and are available for request-level logging. Centralized exception handlers return sanitized error responses instead of exposing unexpected internal exception details. The logging layer includes targeted redaction for selected sensitive patterns; this is not a guarantee that all personally identifiable information (PII) is removed from every log.

**Request IDs:**

Every HTTP request receives a unique request ID (UUID) that is:
- Added to the `X-Request-ID` response header
- Available via `request.state.request_id` in endpoints
- Included in all log statements for correlation
- Can be supplied via `X-Request-ID` request header for external tracing

**Error handling:**

- HTTP exceptions return safe error messages with request IDs
- Validation errors return structured error details
- General exceptions return generic error messages (no internal details exposed)
- All errors are logged with full details server-side
- PII redaction applied to email addresses, credit cards, and SSNs in logs

**Example response headers:**

```
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
```

**Example error response:**

```json
{
  "error": "An internal error occurred",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Security regression tests

Run the focused tests for tenant isolation, upload handling, database migrations, health and observability, and Temporal/Garage behavior:

```bash
uv run pytest tests/test_tenant_isolation.py tests/test_upload_handling.py tests/test_schema_migrations.py tests/test_health_observability.py tests/test_temporal_garage.py -v
```

These tests should be run against the current code before claiming the security fixes are verified.

### DeepEval CI/CD testing

```bash
uv run pytest tests/test_rag_evaluation.py -v
```

Tests cover faithfulness, answer relevancy, contextual relevancy, and end-to-end pipeline quality.

The `.github/workflows/ci.yml` workflow runs DeepEval on every push/PR and RAGAS evaluation when `HF_TOKEN` is available.

Set the GitHub secret:

- `HF_TOKEN` — Hugging Face token for LLM access

---

## What is stored where

| Store | Role |
|-------|------|
| **PostgreSQL** | Document metadata + full node text + vector embeddings + image metadata references |
| **Garage** | Extracted images from PDFs (binary objects) |
| **data/bm25.pkl** | BM25 corpus (gitignored). Generated from PostgreSQL nodes. |
| **Valkey** | Cached retrieval JSON |

Deleting the source PDF on disk does **not** remove the document from Postgres. Query still works until you delete the `documents` row (nodes and images cascade via `ON DELETE CASCADE`) and rebuild indexes.

### Rebuilding BM25

`bm25.pkl` is a local derived artifact. Regenerate it whenever the PostgreSQL document corpus changes (after ingest or deletion):

```bash
uv run python scripts/rebuild_bm25.py
```

---

## License

Add a license file if you want others to reuse this project (for example MIT).
