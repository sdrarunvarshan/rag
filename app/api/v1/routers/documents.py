from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse, Response

from app.services.auth_service import get_current_user
from app.services.document_service import (
    delete_document_endpoint,
    document_images,
    list_user_documents,
    list_user_query_history,
    load_image,
    remove_query_history,
)

router = APIRouter(tags=["documents"])


@router.get("/documents")
def documents(current_user: dict = Depends(get_current_user)) -> dict:
    return list_user_documents(current_user)


@router.get("/query-history")
def query_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
) -> dict:
    return list_user_query_history(current_user, limit=limit)


@router.delete("/query-history/{query_id}")
def delete_query_history(
    query_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    return remove_query_history(query_id, current_user)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    return delete_document_endpoint(document_id, current_user)


@router.get("/documents/{document_id}/images")
def images(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    return document_images(document_id, current_user)


@router.get("/images/{image_id}")
def image_file(
    image_id: str,
    current_user: dict = Depends(get_current_user),
):
    loaded = load_image(image_id, current_user)
    if isinstance(loaded, str):
        return RedirectResponse(url=loaded)
    data, mime_type = loaded
    return Response(content=data, media_type=mime_type)
