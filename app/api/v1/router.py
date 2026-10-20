from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers import admin, auth, documents, health, ingest, queries, roles, users


def build_v1_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health.router)
    router.include_router(auth.router)
    router.include_router(users.router)
    router.include_router(roles.router)
    router.include_router(documents.router)
    router.include_router(queries.router)
    router.include_router(ingest.router)
    router.include_router(admin.router)
    return router
