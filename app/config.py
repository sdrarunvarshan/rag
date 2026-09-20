from pathlib import Path
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/rag",
)
DATABASE_URL_FALLBACK = os.getenv(
    "DATABASE_URL_FALLBACK",
    "postgresql://1234:1234@localhost:5432/rag",
)
VALKEY_URL = os.getenv("VALKEY_URL", "redis://127.0.0.1:6379/0")
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_API_KEY = HF_TOKEN or OPENAI_API_KEY
OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL", "https://router.huggingface.co/v1"
)
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
# Qwen3.5-0.8B is not hosted on the HF Inference router; use 9B there,
# or point OPENAI_BASE_URL at a local vLLM/SGLang server for 0.8B.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "Qwen/Qwen3.5-9B")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.8"))
LLM_PRESENCE_PENALTY = float(os.getenv("LLM_PRESENCE_PENALTY", "1.5"))
LLM_TOP_K = int(os.getenv("LLM_TOP_K", "20"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

DATA_DIR = ROOT / "data"
BM25_PATH = DATA_DIR / "bm25.pkl"
UPLOAD_DIR = DATA_DIR / "uploads"

TOP_K_VECTOR = int(os.getenv("TOP_K_VECTOR", "20"))
TOP_K_BM25 = int(os.getenv("TOP_K_BM25", "20"))
RRF_K = int(os.getenv("RRF_K", "60"))
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "15"))
TOP_SECTIONS = int(os.getenv("TOP_SECTIONS", "4"))
MAX_SIBLINGS = int(os.getenv("MAX_SIBLINGS", "2"))
MAX_CHILDREN = int(os.getenv("MAX_CHILDREN", "8"))
MAX_TABLES = int(os.getenv("MAX_TABLES", "6"))
CONTEXT_CHAR_BUDGET = int(os.getenv("CONTEXT_CHAR_BUDGET", "12000"))
TABLE_RERANK_BONUS = float(os.getenv("TABLE_RERANK_BONUS", "0.15"))


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
