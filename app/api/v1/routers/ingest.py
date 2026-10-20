from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.services.auth_service import get_current_user
from app.services.ingest_service import ingest as ingest_document

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    return await ingest_document(request, file, current_user)
