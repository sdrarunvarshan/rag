from __future__ import annotations

import logging
from uuid import UUID, uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import (
    GARAGE_ACCESS_KEY,
    GARAGE_BUCKET,
    GARAGE_ENDPOINT,
    GARAGE_REGION,
    GARAGE_SECRET_KEY,
    GARAGE_SECURE,
)

log = logging.getLogger(__name__)

_boto3_client = None


def _clean_endpoint(endpoint: str) -> str:
    raw = (endpoint or "").strip()

    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    scheme = "https://" if GARAGE_SECURE else "http://"
    return f"{scheme}{raw}"


def _get_boto3_client():
    global _boto3_client

    if _boto3_client is None:
        endpoint_url = _clean_endpoint(GARAGE_ENDPOINT)

        _boto3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=GARAGE_ACCESS_KEY,
            aws_secret_access_key=GARAGE_SECRET_KEY,
            region_name=GARAGE_REGION,
            config=Config(
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    return _boto3_client


def ping() -> bool:
    try:
        endpoint_url = _clean_endpoint(GARAGE_ENDPOINT)

        fast_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=GARAGE_ACCESS_KEY,
            aws_secret_access_key=GARAGE_SECRET_KEY,
            region_name=GARAGE_REGION,
            config=Config(
                s3={"addressing_style": "path"},
                connect_timeout=1,
                read_timeout=1,
                retries={"max_attempts": 0},
            ),
        )

        fast_client.list_buckets()
        return True

    except Exception as exc:
        log.warning("Garage ping failed: %s", exc)
        return False


def ensure_bucket() -> None:
    client = _get_boto3_client()

    try:
        client.head_bucket(Bucket=GARAGE_BUCKET)

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=GARAGE_BUCKET)
            log.info("Created Garage bucket: %s", GARAGE_BUCKET)
        else:
            log.error("Failed to check Garage bucket: %s", exc)
            raise

    except Exception as exc:
        log.error("Failed to ensure Garage bucket: %s", exc)
        raise


def upload_image(
    document_id: UUID,
    image_data: bytes,
    mime_type: str,
    image_id: UUID | None = None,
) -> str:
    ensure_bucket()

    if image_id is None:
        image_id = uuid4()

    object_key = (
        f"documents/{document_id}/images/"
        f"{image_id}.{_get_extension(mime_type)}"
    )

    try:
        client = _get_boto3_client()

        client.put_object(
            Bucket=GARAGE_BUCKET,
            Key=object_key,
            Body=image_data,
            ContentType=mime_type,
        )

        log.info("Uploaded image to Garage: %s", object_key)
        return object_key

    except Exception as exc:
        log.error("Failed to upload image to Garage: %s", exc)
        raise


def get_image_url(
    object_key: str,
    expires_in_hours: int = 24,
) -> str:
    try:
        client = _get_boto3_client()

        return client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": GARAGE_BUCKET,
                "Key": object_key,
            },
            ExpiresIn=expires_in_hours * 3600,
        )

    except Exception as exc:
        log.error("Failed to generate presigned URL: %s", exc)
        raise


def get_image_bytes(object_key: str) -> tuple[bytes, str]:
    try:
        client = _get_boto3_client()

        response = client.get_object(
            Bucket=GARAGE_BUCKET,
            Key=object_key,
        )

        data = response["Body"].read()
        content_type = response.get("ContentType") or "image/png"

        return data, content_type

    except Exception as exc:
        log.error("Failed to fetch image bytes from Garage: %s", exc)
        raise


def delete_image(object_key: str) -> None:
    try:
        client = _get_boto3_client()

        client.delete_object(
            Bucket=GARAGE_BUCKET,
            Key=object_key,
        )

        log.info("Deleted image from Garage: %s", object_key)

    except Exception as exc:
        log.error("Failed to delete image from Garage: %s", exc)
        raise


def delete_document_images(document_id: UUID) -> None:
    """Delete all images stored in Garage under this document's prefix."""

    prefix = f"documents/{document_id}/images/"

    try:
        client = _get_boto3_client()

        paginator = client.get_paginator("list_objects_v2")

        deleted_count = 0

        for page in paginator.paginate(
            Bucket=GARAGE_BUCKET,
            Prefix=prefix,
        ):
            contents = page.get("Contents", [])

            if not contents:
                continue

            delete_keys = [
                {"Key": obj["Key"]}
                for obj in contents
            ]

            client.delete_objects(
                Bucket=GARAGE_BUCKET,
                Delete={"Objects": delete_keys},
            )

            deleted_count += len(delete_keys)

        log.info(
            "Deleted %d images for document %s from Garage",
            deleted_count,
            document_id,
        )

    except Exception as exc:
        log.error(
            "Failed to delete document images from Garage: %s",
            exc,
        )
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

    return mime_to_ext.get(
        mime_type.lower(),
        "bin",
    )