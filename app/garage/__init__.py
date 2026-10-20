"""Garage object storage client."""

from app.garage.client import (
    delete_document_images,
    delete_garage_object,
    ensure_bucket,
    get_image_bytes,
    get_image_url,
    ping,
    reconcile_garage_objects,
    upload_image,
    upload_pdf,
)

__all__ = [
    "delete_document_images",
    "delete_garage_object",
    "ensure_bucket",
    "get_image_bytes",
    "get_image_url",
    "ping",
    "reconcile_garage_objects",
    "upload_image",
    "upload_pdf",
]
