from __future__ import annotations

import logging
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

from minio import Minio
from minio.error import S3Error

from app.config import (
    GARAGE_ACCESS_KEY,
    GARAGE_BUCKET,
    GARAGE_ENDPOINT,
    GARAGE_REGION,
    GARAGE_SECRET_KEY,
    GARAGE_SECURE,
)

log = logging.getLogger(__name__)

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            GARAGE_ENDPOINT,
            access_key=GARAGE_ACCESS_KEY,
            secret_key=GARAGE_SECRET_KEY,
            secure=GARAGE_SECURE,
            region=GARAGE_REGION,
        )
    return _client


def ensure_bucket() -> None:
    client = _get_client()
    try:
        if not client.bucket_exists(GARAGE_BUCKET):
            client.make_bucket(GARAGE_BUCKET, region=GARAGE_REGION)
            log.info("Created Garage bucket: %s", GARAGE_BUCKET)
    except S3Error as exc:
        log.error("Failed to ensure Garage bucket: %s", exc)
        raise


def upload_image(
    document_id: UUID,
    image_data: bytes,
    mime_type: str,
    image_id: UUID | None = None,
) -> str:
    client = _get_client()
    ensure_bucket()

    if image_id is None:
        image_id = uuid4()

    object_key = f"documents/{document_id}/images/{image_id}.{_get_extension(mime_type)}"

    try:
        client.put_object(
            GARAGE_BUCKET,
            object_key,
            BytesIO(image_data),
            length=len(image_data),
            content_type=mime_type,
        )
        log.info("Uploaded image to Garage: %s", object_key)
        return object_key
    except S3Error as exc:
        log.error("Failed to upload image to Garage: %s", exc)
        raise


def get_image_url(object_key: str, expires_in_hours: int = 24) -> str:
    client = _get_client()
    try:
        url = client.presigned_get_object(
            GARAGE_BUCKET,
            object_key,
            expires=expires_in_hours * 3600,
        )
        return url
    except S3Error as exc:
        log.error("Failed to generate presigned URL: %s", exc)
        raise


def delete_image(object_key: str) -> None:
    client = _get_client()
    try:
        client.remove_object(GARAGE_BUCKET, object_key)
        log.info("Deleted image from Garage: %s", object_key)
    except S3Error as exc:
        log.error("Failed to delete image from Garage: %s", exc)
        raise


def delete_document_images(document_id: UUID) -> None:
    client = _get_client()
    try:
        prefix = f"documents/{document_id}/images/"
        objects = client.list_objects(GARAGE_BUCKET, prefix=prefix, recursive=True)
        for obj in objects:
            client.remove_object(GARAGE_BUCKET, obj.object_name)
            log.info("Deleted image from Garage: %s", obj.object_name)
    except S3Error as exc:
        log.error("Failed to delete document images from Garage: %s", exc)
        raise


def _get_extension(mime_type: str) -> str:
    mime_to_ext = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
    }
    return mime_to_ext.get(mime_type.lower(), "bin")


def ping() -> bool:
    try:
        client = _get_client()
        client.list_buckets()
        return True
    except S3Error as exc:
        log.warning("Garage ping failed: %s", exc)
        return False
