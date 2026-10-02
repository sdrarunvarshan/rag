# Structure-Aware RAG

A structure-aware Retrieval-Augmented Generation (RAG) system for PDF documents.

PDF documents are parsed with **Docling** into a structured heading/table hierarchy and indexed at **section, subsection, and table** granularity. The system does **not** use fixed-size token chunking.

At query time, **LangGraph** orchestrates the `retrieve → generate` pipeline. Retrieval uses query understanding, hybrid dense + lexical search, Reciprocal Rank Fusion (RRF), reranking, hierarchical expansion, table retrieval, and structured context organization.

Generation uses **LangChain `ChatOpenAI`** with the **Hugging Face Inference Router** and a Qwen model.

The `/query` API exposes a `flow` object containing the individual retrieval and generation stages for debugging and inspection.

---

# Architecture

## Ingest Pipeline

```text
USER UPLOADS PDF
        │
        ▼
    FastAPI
        │
        ▼
     Docling
        │
   ┌────┴───────────────┐
   │                    │
   ▼                    ▼
Text / Tables       Extracted Images
   │                    │
   ▼                    ▼
Structured          Garage
Document Tree       S3-compatible
   │                object storage
   ▼                    │
PostgreSQL               │
+ pgvector               │
+ metadata               │
                        ▼
                   PostgreSQL
                   image references
```

Temporal can optionally be placed between FastAPI and Docling for durable workflow execution:

```text
USER
  │
  ▼
FastAPI
  │
  ├───────────────┐
  │               │
  ▼               ▼
Direct ingest   Temporal
  │               │
  │               ▼
  │           Docling
  │               │
  └───────┬───────┘
          ▼
 Structured Document Tree
```

When Temporal is unavailable, the application can execute the ingest pipeline directly.

---

# Text and Table Pipeline

```text
PDF
 │
 ▼
Docling
 │
 ▼
Structured Document Tree
 │
 ├── Documents
 ├── Sections
 ├── Subsections
 └── Tables
      │
      ▼
PostgreSQL
      │
      ├── Full node text
      ├── Metadata
      └── pgvector embeddings
```

BM25 is generated from the PostgreSQL node corpus and stored locally as a derived artifact.

```text
PostgreSQL Nodes
      │
      ▼
   BM25 Index
      │
      ▼
data/bm25.pkl
```

---

# Image Pipeline

Docling extracts images from PDFs.

```text
PDF
 │
 ▼
Docling
 │
 ▼
Extracted Images
 │
 ├───────────────┐
 ▼               ▼
Garage       PostgreSQL
S3 storage   image metadata
```

Garage stores the binary image objects.

PostgreSQL stores metadata and references to those objects.

Garage is **not used as the PostgreSQL replacement** and is not the source of truth for the document tree.

---

# Query Pipeline

```text
USER QUESTION
      │
      ▼
Query Understanding
app/query_understand.py
      │
      ▼
Query Type + Scope + Concepts
definition | comparison | numeric | ...
      │
      ├───────────────────────────┐
      ▼                           ▼
Dense Retrieval                 BM25
      │                           │
pgvector +                       │
sentence-transformers            │
app/index.py                     │
      │                           │
      └─────────────┬─────────────┘
                    ▼
              RRF Fusion
           app/retrieve.py
                    │
                    ▼
                Reranker
       embedding similarity
             + table boost
                    │
                    ▼
       Hierarchical Expansion
          ┌────────┼────────┐
          ▼        ▼        ▼
        Parent   Sibling  Children
                    │
                    ▼
             Table Retrieval
                    │
                    ▼
            Context Organizer
                    │
                    ▼
          Structured Context
                    │
                    ▼
       LangGraph retrieve → generate
          app/langgraph_rag.py
                    │
                    ▼
             LangChain + Qwen
                 app/llm.py
                    │
                    ▼
             Grounded Answer
```

---

# Retrieval Stages

| Stage                  | What it does                                                | Code                                      |
| ---------------------- | ----------------------------------------------------------- | ----------------------------------------- |
| Query Understanding    | Determines query type, scope, concepts, and expansion flags | `app/query_understand.py`                 |
| Dense Retrieval        | Searches pgvector embeddings                                | `app/index.py` / `app/pgvector_search.py` |
| BM25                   | Performs lexical retrieval over indexed nodes               | `app/index.py`                            |
| RRF Fusion             | Combines dense and lexical rankings                         | `app/retrieve.py`                         |
| Reranker               | Re-scores fused candidates using embedding similarity       | `app/retrieve.py`                         |
| Hierarchical Expansion | Adds parent, sibling, and child sections                    | `app/retrieve.py`                         |
| Table Retrieval        | Retrieves relevant table nodes                              | `app/retrieve.py`                         |
| Context Organizer      | Orders and labels context blocks                            | `app/retrieve.py`                         |
| LangGraph              | Orchestrates retrieval and generation                       | `app/langgraph_rag.py`                    |
| LangChain + Qwen       | Generates the grounded answer                               | `app/llm.py`                              |

The API returns a `flow` object so the retrieval process can be inspected stage by stage.

---

# MCP Interface

The RAG pipeline is also exposed through the **Model Context Protocol (MCP)** using FastMCP.

```text
AI Client
    │
    ▼
MCP Client
    │
    ▼
FastMCP
stdio transport
    │
    ▼
RAG Tools
    │
    ├── query_document
    ├── retrieve_document_context
    ├── get_document
    ├── get_document_images
    ├── cache_health
    └── rag_health
    │
    ▼
Existing RAG Pipeline
    │
    ▼
LangGraph
    │
    ▼
Retrieval → Qwen
```

---

# Features

* Structure-aware PDF ingestion
* Docling-based document parsing
* Heading and table hierarchy
* No fixed-size sliding-window chunking
* Section, subsection, and table-level indexing
* Image extraction from PDFs
* Garage S3-compatible object storage for extracted images
* PostgreSQL as the source of truth
* PostgreSQL image metadata references
* pgvector dense retrieval
* Sentence-transformers embeddings
* BM25 lexical retrieval
* Reciprocal Rank Fusion (RRF)
* Embedding-based reranking
* Table-aware reranking
* Hierarchical parent/sibling/child expansion
* Structured context organization
* Query understanding
* Optional `document_id` filtering
* Valkey/Redis-compatible retrieval cache
* LangGraph retrieval → generation orchestration
* LangChain integration
* Qwen generation through Hugging Face Inference Router
* MCP interface through FastMCP
* MCP-based AI agent with tool calling
* Optional Temporal durable workflows
* OpenTelemetry instrumentation
* Arize Phoenix observability
* RAGAS evaluation
* DeepEval CI/CD testing
* API `flow` tracing for retrieval debugging

---

# Technology Stack

| Layer               | Technology                             |
| ------------------- | -------------------------------------- |
| API                 | FastAPI + Uvicorn                      |
| MCP                 | FastMCP                                |
| PDF Parsing         | Docling                                |
| ORM                 | SQLAlchemy                             |
| Database Migrations | Alembic                                |
| Database            | PostgreSQL                             |
| Vector Search       | pgvector                               |
| Embeddings          | sentence-transformers                  |
| Lexical Search      | rank-bm25                              |
| Object Storage      | Garage                                 |
| Cache               | Valkey / Redis protocol                |
| LLM                 | Qwen via Hugging Face Inference Router |
| LLM Client          | LangChain `ChatOpenAI`                 |
| Orchestration       | LangGraph                              |
| Durable Workflows   | Temporal                               |
| Observability       | OpenTelemetry + Arize Phoenix          |
| Evaluation          | RAGAS + DeepEval                       |

---

# Repository Layout

```text
rag/
│
├── app/
│   ├── main.py
│   │   FastAPI routes:
│   │   /health
│   │   /documents
│   │   /ingest
│   │   /query
│   │
│   ├── my_server.py
│   │   FastMCP server and RAG tools
│   │
│   ├── agent.py
│   │   AI agent using MCP tools and Qwen
│   │
│   ├── test_agent.py
│   │   MCP connectivity test
│   │
│   ├── ingest.py
│   │   Docling PDF ingestion
│   │
│   ├── query_understand.py
│   │   Query type, scope, concepts and expansion planning
│   │
│   ├── db.py
│   │   PostgreSQL queries
│   │
│   ├── models.py
│   │   SQLAlchemy models
│   │
│   ├── index.py
│   │   pgvector + BM25 indexing
│   │
│   ├── pgvector_search.py
│   │   pgvector search
│   │
│   ├── retrieve.py
│   │   Hybrid retrieval, RRF, reranking,
│   │   hierarchy, tables and context organization
│   │
│   ├── langgraph_rag.py
│   │   LangGraph retrieve → generate pipeline
│   │
│   ├── llm.py
│   │   LangChain ChatOpenAI + Hugging Face router
│   │
│   ├── cache.py
│   │   Valkey cache
│   │
│   ├── config.py
│   │   Environment configuration
│   │
│   ├── garage_client.py
│   │   Garage S3-compatible image storage
│   │
│   ├── telemetry.py
│   │   OpenTelemetry + Phoenix
│   │
│   ├── evaluation.py
│   │   RAGAS evaluation
│   │
│   ├── temporal_activities.py
│   │   Temporal activities
│   │
│   ├── temporal_workflows.py
│   │   Temporal workflows
│   │
│   └── temporal_worker.py
│       Temporal worker
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── scripts/
│   ├── ingest_pdf.py
│   ├── check_services.py
│   ├── rebuild_bm25.py
│   └── start_phoenix.py
│
├── tests/
│   └── test_rag_evaluation.py
│
├── data/
│   └── bm25.pkl
│
├── garage-config.toml
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── alembic.ini
```

---

# Prerequisites

* Python 3.10+
* `uv`
* PostgreSQL
* PostgreSQL `pgvector` extension
* Valkey or Redis-compatible server
* Docker Desktop
* Garage
* Hugging Face access token
* Temporal Server — optional
* Arize Phoenix — optional

---

# Database

Create the PostgreSQL database:

```sql
CREATE DATABASE rag;
```

The application uses Alembic to manage database schema migrations.

Run migrations:

```bash
uv run alembic upgrade head
```

Create a migration after changing SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "Description of changes"
```

Rollback the previous migration:

```bash
uv run alembic downgrade -1
```

Default database URL:

```env
DATABASE_URL=postgresql://postgres:1234@localhost:5432/rag
```

Update the credentials if your PostgreSQL installation uses different values.

---

# Garage Object Storage

Garage is used as the S3-compatible object store for extracted PDF images.

The project uses a **single-node Garage deployment for local development**.

Garage runs inside Docker while the FastAPI application runs directly on the host.

```text
Windows Host
│
├── FastAPI :8000
├── PostgreSQL :5432
└── Valkey :6379
        │
        │
        ▼
Docker
└── Garage
    ├── S3 API :3900
    └── Admin API :3902
```

FastAPI connects to Garage through:

```text
http://localhost:3900
```

---

# Garage Configuration

The project uses the existing:

```text
garage-config.toml
```

Do not create a second Garage configuration file.

Example configuration:

```toml
metadata_dir = "/data/meta"
data_dir = "/data/data"
db_engine = "lmdb"

replication_factor = 1

rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "YOUR_RPC_SECRET"

[s3_api]
s3_region = "garage"
api_bind_addr = "[::]:3900"

[admin]
api_bind_addr = "[::]:3902"
admin_token = "CHANGE_THIS_ADMIN_TOKEN"
metrics_token = "CHANGE_THIS_METRICS_TOKEN"
```

For local development, `replication_factor = 1` is appropriate for a single Garage node.

---

# Docker Compose

Use the following `docker-compose.yml`:

```yaml
services:
  garage:
    image: dxflrs/garage:v2.4.0
    container_name: garage
    ports:
      - "3900:3900"
      - "3902:3902"
    environment:
      - RUST_LOG=info
    volumes:
      - garage_data:/data
      - ./garage-config.toml:/etc/garage.toml:ro
    command: /garage server
    restart: unless-stopped

volumes:
  garage_data:
```

### Why `/garage server`?

The Garage Docker image already provides `/garage` as the executable.

The configuration file is mounted at:

```text
/etc/garage.toml
```

Garage automatically loads the configuration from that location.

Do **not** use:

```text
server /etc/garage.toml
```

or:

```text
/garage server /etc/garage.toml
```

for this Docker image.

---

# Start Garage

From the project directory:

```powershell
docker compose up -d garage
```

Check the container:

```powershell
docker compose ps
```

You should see Garage running.

Check the Garage node:

```powershell
docker exec garage /garage status
```

---

# Initialize Garage Layout

A fresh Garage installation must have a layout before buckets and access keys can be created.

First obtain the node ID:

```powershell
docker exec garage /garage status
```

Copy the node ID from the output.

For example:

```text
749d67c4b25532e4
```

Assign the node to a zone:

```powershell
docker exec garage /garage layout assign 749d67c4b25532e4 -z dc1 -c 1G
```

Check the layout:

```powershell
docker exec garage /garage layout show
```

The output will show a pending layout version.

Apply the pending version:

```powershell
docker exec garage /garage layout apply --version <PENDING_VERSION>
```

For example, if `layout show` reports version `1`:

```powershell
docker exec garage /garage layout apply --version 1
```

Do not permanently hard-code `1` in automation or documentation. Use the pending version reported by:

```powershell
docker exec garage /garage layout show
```

---

# Create Garage Access Key

After the layout has been applied:

```powershell
docker exec garage /garage key create rag-app
```

List keys:

```powershell
docker exec garage /garage key list
```

The command output provides the access key ID and secret key.

Save these values securely.

---

# Create Garage Bucket

Create the bucket:

```powershell
docker exec garage /garage bucket create rag-documents
```

List buckets:

```powershell
docker exec garage /garage bucket list
```

Allow the application key to access the bucket:

```powershell
docker exec garage /garage bucket allow --read --write --owner rag-documents --key rag-app
```

Check the bucket:

```powershell
docker exec garage /garage bucket info rag-documents
```

---

# Garage Environment Variables

Update `.env` with the actual Garage credentials generated by Garage.

```env
GARAGE_ENDPOINT=http://localhost:3900
GARAGE_ACCESS_KEY=<YOUR_GARAGE_ACCESS_KEY>
GARAGE_SECRET_KEY=<YOUR_GARAGE_SECRET_KEY>
GARAGE_SECURE=false
GARAGE_BUCKET=rag-documents
GARAGE_REGION=garage
```

Do not use placeholder values such as:

```env
GARAGE_ACCESS_KEY=garage-key
GARAGE_SECRET_KEY=garage-secret
```

unless those are actually the credentials generated by your Garage instance.

---

# Garage Web/Admin Endpoint

Garage's configured admin endpoint is:

```text
http://localhost:3902
```

The S3 API used by the RAG application is:

```text
http://localhost:3900
```

The RAG application does **not** need the Garage RPC port for normal S3 operations.

The RPC port is used for Garage node-to-node communication.

---

# Verify Garage

Run:

```powershell
docker exec garage /garage status
```

Then:

```powershell
docker exec garage /garage bucket info rag-documents
```

You can also run the project's service check:

```powershell
uv run python scripts/check_services.py
```

The Garage health check should be able to reach:

```text
http://localhost:3900
```

---

# Windows Setup

Create the Python environment:

```powershell
uv venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
uv pip install -r requirements.txt
```

Copy the environment file:

```powershell
copy .env.example .env
```

Edit `.env` and configure:

* PostgreSQL
* Valkey
* Garage
* Hugging Face
* Temporal if required
* Phoenix if required

---

# Environment Variables

| Variable               | Purpose                       |
| ---------------------- | ----------------------------- |
| `DATABASE_URL`         | PostgreSQL connection string  |
| `VALKEY_URL`           | Valkey/Redis-compatible cache |
| `HF_TOKEN`             | Hugging Face access token     |
| `OPENAI_BASE_URL`      | LLM API endpoint              |
| `OPENAI_MODEL`         | Qwen model                    |
| `LLM_MAX_TOKENS`       | Maximum generation tokens     |
| `LLM_TEMPERATURE`      | LLM temperature               |
| `LLM_TOP_P`            | Top-p sampling                |
| `LLM_PRESENCE_PENALTY` | Presence penalty              |
| `LLM_TOP_K`            | Qwen top-k parameter          |
| `EMBEDDING_MODEL`      | Sentence-transformers model   |
| `CACHE_TTL_SECONDS`    | Retrieval cache TTL           |
| `TEMPORAL_HOST`        | Temporal server host          |
| `TEMPORAL_PORT`        | Temporal server port          |
| `TEMPORAL_NAMESPACE`   | Temporal namespace            |
| `TEMPORAL_TASK_QUEUE`  | Temporal task queue           |
| `GARAGE_ENDPOINT`      | Garage S3 endpoint            |
| `GARAGE_ACCESS_KEY`    | Garage access key             |
| `GARAGE_SECRET_KEY`    | Garage secret key             |
| `GARAGE_SECURE`        | Whether Garage uses HTTPS     |
| `GARAGE_BUCKET`        | Garage bucket                 |
| `GARAGE_REGION`        | Garage S3 region              |
| `PHOENIX_ENDPOINT`     | Phoenix endpoint              |
| `PHOENIX_PROJECT_NAME` | Phoenix project name          |

Example:

```env
DATABASE_URL=postgresql://postgres:1234@localhost:5432/rag

VALKEY_URL=redis://127.0.0.1:6379

HF_TOKEN=your_huggingface_token

OPENAI_BASE_URL=https://router.huggingface.co/v1
OPENAI_MODEL=Qwen/Qwen3.5-9B

LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.7
LLM_TOP_P=0.8
LLM_PRESENCE_PENALTY=1.5
LLM_TOP_K=20

EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

CACHE_TTL_SECONDS=3600

TEMPORAL_HOST=localhost
TEMPORAL_PORT=7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=rag-task-queue

GARAGE_ENDPOINT=http://localhost:3900
GARAGE_ACCESS_KEY=your_garage_access_key
GARAGE_SECRET_KEY=your_garage_secret_key
GARAGE_SECURE=false
GARAGE_BUCKET=rag-documents
GARAGE_REGION=garage

PHOENIX_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=rag-evaluation
```

Never commit `.env`.

---

# Local Qwen Server

The Hugging Face router can be replaced by a local OpenAI-compatible Qwen server.

For example:

```env
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_MODEL=Qwen/Qwen3.5-0.9B
```

Keep the RAG API on:

```text
8000
```

and the local LLM server on:

```text
8001
```

---

# Valkey

Valkey is optional but recommended for retrieval caching.

The application uses the Redis protocol.

Example:

```env
VALKEY_URL=redis://127.0.0.1:6379
```

If Valkey is running inside WSL and Windows needs to access it, configure Valkey to listen on an address reachable from Windows.

Example:

```bash
valkey-server --bind 0.0.0.0 --port 6379 --protected-mode no
```

Alternatively, configure `VALKEY_URL` with the WSL IP address.

---

# Database Migrations

Apply migrations:

```bash
uv run alembic upgrade head
```

Create a migration:

```bash
uv run alembic revision --autogenerate -m "Description of changes"
```

View migration history:

```bash
uv run alembic history
```

Rollback:

```bash
uv run alembic downgrade -1
```

---

# Start the Application

Start FastAPI:

```powershell
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

Swagger/OpenAPI:

```text
http://127.0.0.1:8000/docs
```

Restart Uvicorn after changing `.env`.

---

# API

| Method | Endpoint                          | Description                          |
| ------ | --------------------------------- | ------------------------------------ |
| `GET`  | `/health`                         | PostgreSQL, Valkey and Garage health |
| `GET`  | `/documents`                      | List indexed documents               |
| `GET`  | `/documents/{document_id}/images` | Get extracted images                 |
| `POST` | `/ingest`                         | Upload and ingest a PDF              |
| `POST` | `/query`                          | Query the RAG system                 |

---

# Ingest a PDF

Using the CLI:

```powershell
uv run python scripts/ingest_pdf.py ./paper.pdf
```

Or through the API:

```bash
curl -F "file=@./paper.pdf" http://127.0.0.1:8000/ingest
```

The ingest pipeline:

```text
PDF
 │
 ▼
Docling
 │
 ├── Text
 │     └── PostgreSQL + pgvector
 │
 ├── Tables
 │     └── PostgreSQL + pgvector
 │
 └── Images
       ├── Garage
       └── PostgreSQL metadata
```

The response includes the generated `document_id`.

After ingestion, the original PDF file does not need to remain on the local filesystem for querying, because the indexed document data is stored in PostgreSQL and extracted images are stored in Garage.

---

# Query

Example:

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What is the project title?\",\"document_id\":\"<uuid>\"}"
```

`document_id` is optional.

Without a `document_id`, the system searches the full indexed corpus.

---

# Query Response

The response contains:

```text
answer
query_plan
sources
structured
context
flow
llm_skipped
```

### `answer`

The grounded answer generated by Qwen.

### `query_plan`

Contains:

* query type
* scope
* concepts
* expansion flags

### `sources`

Expanded document sections used for context.

### `structured`

Ordered context blocks with roles such as:

* parent
* sibling
* child
* table
* hit

### `context`

The structured context passed to the LLM.

### `flow`

Stage-by-stage retrieval trace:

```text
understand
→ vector
→ bm25
→ hybrid
→ rerank
→ hierarchy
→ tables
→ context
→ llm
```

### `llm_skipped`

Indicates whether generation was skipped or failed.

The model is instructed to answer only from the retrieved context. If the retrieved document context does not contain enough information, the system can return an insufficient-context response instead of inventing information.

---

# MCP Server

The project exposes the RAG pipeline through FastMCP.

Start the MCP server:

```powershell
uv run python -m app.my_server
```

The MCP server uses:

```text
stdio
```

transport.

---

# MCP Tools

| Tool                        | Description                          |
| --------------------------- | ------------------------------------ |
| `query_document`            | Runs the complete RAG pipeline       |
| `retrieve_document_context` | Runs retrieval without generation    |
| `get_document`              | Retrieves document metadata          |
| `get_document_images`       | Retrieves extracted image references |
| `cache_health`              | Checks cache and Garage availability |
| `rag_health`                | Returns RAG service health           |

---

# AI Agent

The project includes an AI agent that communicates with the RAG system through MCP.

Architecture:

```text
User
 │
 ▼
AI Agent
 │
 ▼
Qwen
 │
 ▼
Tool Calling
 │
 ▼
MCP Server
 │
 ▼
RAG Tools
 │
 ▼
Existing RAG Pipeline
```

The agent can:

1. Connect to the MCP server
2. Discover available tools
3. Send the available tools to Qwen
4. Allow Qwen to select the required tool
5. Execute the tool
6. Return grounded results

Start the MCP server:

```powershell
uv run python -m app.my_server
```

In another terminal:

```powershell
uv run python -m app.agent
```

---

# Test MCP Connectivity

Run:

```powershell
uv run python -m app.test_agent
```

The test displays:

* MCP connection status
* Available tools
* Tool descriptions

---

# Temporal

Temporal is optional.

It provides durable workflow execution, retries, and workflow recovery.

The application can execute without Temporal using direct execution.

## Start Temporal

For local development:

```bash
temporal server start-dev
```

Temporal normally uses:

```text
localhost:7233
```

Temporal Web UI:

```text
http://localhost:8233
```

---

# Temporal Worker

Start the worker:

```powershell
uv run python -m app.temporal_worker
```

The worker connects to:

```text
localhost:7233
```

and listens on:

```text
rag-task-queue
```

Temporal workflows include:

```text
IngestWorkflow
QueryWorkflow
```

Activities are implemented in:

```text
app/temporal_activities.py
```

Workflows are implemented in:

```text
app/temporal_workflows.py
```

---

# Running Without Temporal

Temporal is not required for normal development.

If Temporal is unavailable, the application executes the RAG operations directly.

This means the following remain available:

* PDF ingestion
* Docling parsing
* PostgreSQL indexing
* pgvector retrieval
* BM25 retrieval
* RRF
* reranking
* hierarchical expansion
* table retrieval
* context organization
* LLM generation
* MCP

The difference is that Temporal-specific durable execution and workflow recovery are unavailable.

---

# Observability

The application supports OpenTelemetry and Arize Phoenix.

Start Phoenix:

```powershell
uv run python scripts/start_phoenix.py
```

Phoenix UI:

```text
http://localhost:6006
```

Configure:

```env
PHOENIX_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=rag-evaluation
```

Phoenix can capture:

* FastAPI traces
* retrieval stages
* LangChain calls
* LLM calls
* query understanding
* context organization
* custom application spans

---

# RAGAS Evaluation

RAGAS can be used to evaluate the RAG pipeline.

Example:

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

Metrics include:

* Faithfulness
* Answer Relevance
* Context Precision
* Context Recall

---

# DeepEval

DeepEval tests can be executed with:

```powershell
uv run pytest tests/test_rag_evaluation.py -v
```

The tests can cover:

* Faithfulness
* Answer relevancy
* Contextual relevancy
* End-to-end RAG quality

---

# CI/CD

The project can run DeepEval tests through GitHub Actions.

The workflow can execute:

```text
Git push / Pull Request
        │
        ▼
GitHub Actions
        │
        ▼
DeepEval
        │
        ▼
RAG quality checks
```

If LLM-based evaluation requires Hugging Face access, configure:

```text
HF_TOKEN
```

as a GitHub Actions secret.

---

# What Is Stored Where?

| Store           | Purpose                        |
| --------------- | ------------------------------ |
| PostgreSQL      | Document metadata              |
| PostgreSQL      | Full structured node text      |
| PostgreSQL      | Image metadata/references      |
| pgvector        | Node embeddings                |
| Garage          | Extracted image binary objects |
| `data/bm25.pkl` | Derived BM25 index             |
| Valkey          | Cached retrieval results       |

Garage is used for **binary image storage**.

PostgreSQL remains the source of truth for:

* documents
* nodes
* structured hierarchy
* image metadata

---

# Document Lifecycle

```text
PDF Upload
    │
    ▼
Docling
    │
    ├───────────────┐
    ▼               ▼
Text/Tables      Images
    │               │
    ▼               ▼
PostgreSQL       Garage
    │               │
    └───────┬───────┘
            │
            ▼
         Retrieval
            │
            ▼
        RAG Query
            │
            ▼
      Grounded Answer
```

Deleting the original PDF from the local filesystem does not delete the indexed document.

The indexed document remains available until its database records are removed.

Deleting the document record from PostgreSQL removes dependent `nodes` and `images` records when the configured database relationships use cascading deletion.

Garage image objects should also be handled according to the application's image-deletion logic if documents are deleted.

---

# Rebuilding BM25

BM25 is a derived index generated from PostgreSQL nodes.

After changing the indexed document corpus, rebuild the BM25 index:

```powershell
uv run python scripts/rebuild_bm25.py
```

Recommended workflow:

```text
PostgreSQL corpus changes
        │
        ▼
Rebuild BM25
        │
        ▼
data/bm25.pkl
```

The BM25 file should normally be excluded from Git if it is generated locally.

---

# Service Startup Order

For local development, the recommended order is:

```text
1. PostgreSQL
        │
        ▼
2. Valkey
        │
        ▼
3. Garage
        │
        ▼
4. Garage layout + bucket + access key
        │
        ▼
5. Alembic migrations
        │
        ▼
6. FastAPI
        │
        ▼
7. Optional Temporal
        │
        ▼
8. Optional Phoenix
        │
        ▼
9. Optional MCP / AI Agent
```

---

# Quick Start

## 1. Start Garage

```powershell
docker compose up -d garage
```

Check:

```powershell
docker compose ps
```

---

## 2. Check Garage

```powershell
docker exec garage /garage status
```

---

## 3. Initialize Garage Layout

Get the node ID:

```powershell
docker exec garage /garage status
```

Assign it:

```powershell
docker exec garage /garage layout assign <NODE_ID> -z dc1 -c 1G
```

Show layout:

```powershell
docker exec garage /garage layout show
```

Apply the pending version:

```powershell
docker exec garage /garage layout apply --version <PENDING_VERSION>
```

---

## 4. Create Garage Key

```powershell
docker exec garage /garage key create rag-app
```

List keys:

```powershell
docker exec garage /garage key list
```

---

## 5. Create Bucket

```powershell
docker exec garage /garage bucket create rag-documents
```

Allow access:

```powershell
docker exec garage /garage bucket allow --read --write --owner rag-documents --key rag-app
```

Verify:

```powershell
docker exec garage /garage bucket info rag-documents
```

---

## 6. Configure `.env`

```env
GARAGE_ENDPOINT=http://localhost:3900
GARAGE_ACCESS_KEY=<GENERATED_ACCESS_KEY>
GARAGE_SECRET_KEY=<GENERATED_SECRET_KEY>
GARAGE_SECURE=false
GARAGE_BUCKET=rag-documents
GARAGE_REGION=garage
```

---

## 7. Install Python Dependencies

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

---

## 8. Run Database Migrations

```powershell
uv run alembic upgrade head
```

---

## 9. Start FastAPI

```powershell
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

---

## 10. Ingest a PDF

```powershell
uv run python scripts/ingest_pdf.py ./paper.pdf
```

---

## 11. Query

```text
POST /query
```

Example question:

```text
What is the project title?
```

---

# Local Development Architecture

The complete local system can run as:

```text
┌──────────────────────────────────────────────┐
│              Windows Host                    │
│                                              │
│  FastAPI                 :8000               │
│  PostgreSQL              :5432               │
│  Valkey                  :6379               │
│  Temporal                :7233  (optional)   │
│  Phoenix                 :6006  (optional)   │
│                                              │
│              │                               │
│              │ S3 API                        │
│              ▼                               │
│        ┌─────────────┐                       │
│        │   Docker    │                       │
│        │             │                       │
│        │   Garage    │                       │
│        │    :3900    │                       │
│        │    :3902    │                       │
│        └─────────────┘                       │
│                                              │
└──────────────────────────────────────────────┘
```

---

# Production Direction

For production deployment, the local single-node configuration should be replaced with an appropriately secured and monitored deployment.

Potential production components include:

```text
                    ┌─────────────┐
                    │   Client    │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   FastAPI   │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        PostgreSQL       Valkey       Garage
        + pgvector                     S3
              │                         │
              └────────────┬────────────┘
                           ▼
                    RAG Retrieval
                           │
                           ▼
                    LangGraph
                           │
                           ▼
                       Qwen LLM
```

Production deployment should additionally address:

* HTTPS/TLS
* secrets management
* database backups
* object-storage backups
* access control
* authentication
* monitoring
* logging
* resource limits
* Garage cluster configuration
* PostgreSQL connection pooling
* LLM rate limits
* cache policies

---

# Troubleshooting

## Garage container is not running

Check:

```powershell
docker compose ps -a
```

View logs:

```powershell
docker logs garage
```

Restart:

```powershell
docker compose down
docker compose up -d garage
```

---

## Garage says `Layout not ready`

Run:

```powershell
docker exec garage /garage status
```

Then:

```powershell
docker exec garage /garage layout show
```

Assign the node:

```powershell
docker exec garage /garage layout assign <NODE_ID> -z dc1 -c 1G
```

Then apply the pending layout version:

```powershell
docker exec garage /garage layout apply --version <PENDING_VERSION>
```

Only after the layout is applied should you create the key and bucket.

---

## Garage S3 connection refused

Verify Garage:

```powershell
docker ps
```

Verify the S3 port:

```text
localhost:3900
```

Verify `.env`:

```env
GARAGE_ENDPOINT=http://localhost:3900
```

If FastAPI is running directly on Windows, `localhost:3900` is correct because Docker publishes Garage's S3 port to the Windows host.

---

## `exec: "server": executable file not found`

Do not use:

```yaml
command: server /etc/garage.toml
```

Use:

```yaml
command: /garage server
```

---

## Garage says `/etc/garage.toml` is a directory

Check the Compose mount:

```yaml
volumes:
  - ./garage-config.toml:/etc/garage.toml:ro
```

Make sure `garage-config.toml` is an actual file in the project directory.

---

## PostgreSQL connection fails

Check PostgreSQL is running and verify:

```env
DATABASE_URL=postgresql://postgres:1234@localhost:5432/rag
```

Then run:

```powershell
uv run alembic upgrade head
```

---

## Valkey unavailable

Valkey is optional.

If unavailable, the main RAG pipeline can still operate without retrieval caching.

Check:

```env
VALKEY_URL=redis://127.0.0.1:6379
```

---

## LLM generation fails

Verify:

```env
HF_TOKEN=your_token
OPENAI_BASE_URL=https://router.huggingface.co/v1
OPENAI_MODEL=Qwen/Qwen3.5-9B
```

Restart Uvicorn after changing `.env`.

---

# Important Storage Boundary

The project intentionally separates storage responsibilities:

```text
PostgreSQL
    │
    ├── Document metadata
    ├── Structured document tree
    ├── Node text
    ├── Image metadata
    └── Vector embeddings

Garage
    │
    └── Extracted image binary objects

Valkey
    │
    └── Temporary retrieval cache

data/bm25.pkl
    │
    └── Derived lexical index
```

This separation allows PostgreSQL to remain the source of truth while Garage handles binary object storage.

---

# License

Add a license file if you want others to reuse or distribute this project.

For example:

```text
MIT License
```

The project should include the actual `LICENSE` file if an open-source license is selected.
