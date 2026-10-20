from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.schemas.query import QueryRequest, QueryResponse
from app.services.auth_service import get_current_user
from app.services.query_service import answer_query, stream_query

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    request: Request,
    body: QueryRequest,
    current_user: dict = Depends(get_current_user),
) -> QueryResponse:
    return await answer_query(request, body, current_user)


@router.post("/query/stream")
def query_stream(
    request: Request,
    body: QueryRequest,
    current_user: dict = Depends(get_current_user),
):
    return stream_query(request, body, current_user)
