from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    document_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    cached: bool
    sources: list[dict]
    images: list[dict] = Field(default_factory=list)
    context: str
    flow: dict[str, dict]
    llm_skipped: bool = False
    query_plan: dict = Field(default_factory=dict)
    structured: list[dict] = Field(default_factory=list)
