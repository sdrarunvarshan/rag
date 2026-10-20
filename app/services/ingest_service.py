from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, UploadFile

from app.repositories import ping
from app.config import MAX_UPLOAD_SIZE_BYTES, TEMPORAL_TASK_QUEUE
from app.core import runtime
from app.ingest import ingest_pdf
from app.middleware import stream_upload_to_disk
from app.temporal_workflows import IngestParams, IngestWorkflow

log = logging.getLogger(__name__)


async def ingest(
    request: Request,
    file: UploadFile,
    current_user: dict,
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file")

    if not ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")

    request_id = getattr(request.state, "request_id", "unknown")
    temp_path: Path | None = None
    direct_temp_path: Path | None = None
    garage_key: str | None = None
    completed = False
    document_id = str(uuid4())

    try:
        try:
            temp_path = await stream_upload_to_disk(file, MAX_UPLOAD_SIZE_BYTES)
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("Upload streaming failed, request_id=%s", request_id)
            raise HTTPException(status_code=500, detail=f"Failed to process file upload: {str(exc)}") from exc

        from app.garage_client import upload_pdf

        pdf_bytes = temp_path.read_bytes()
        garage_key = upload_pdf(pdf_bytes, UUID(document_id), file.filename)

        if runtime.temporal_client:
            log.info(
                "Using Temporal workflow for ingest, request_id=%s, document_id=%s",
                request_id,
                document_id,
            )
            workflow_id = f"ingest-{uuid4()}"
            result = await runtime.temporal_client.execute_workflow(
                IngestWorkflow.run,
                IngestParams(
                    garage_key=garage_key,
                    filename=file.filename,
                    user_id=current_user["id"],
                    document_id=document_id,
                ),
                id=workflow_id,
                task_queue=TEMPORAL_TASK_QUEUE,
            )
        else:
            log.info(
                "Using direct execution for ingest (Temporal unavailable), request_id=%s, document_id=%s",
                request_id,
                document_id,
            )
            from app.garage_client import delete_garage_object, get_image_bytes

            pdf_bytes, _ = get_image_bytes(garage_key)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(pdf_bytes)
                direct_temp_path = Path(handle.name)
            result = ingest_pdf(direct_temp_path, filename=file.filename, user_id=current_user["id"])
            try:
                delete_garage_object(garage_key)
                garage_key = None
            except Exception as cleanup_exc:
                log.warning(
                    "Staging PDF cleanup failed after a successful direct ingest, request_id=%s: %s",
                    request_id,
                    cleanup_exc,
                )
        completed = True
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Ingest failed, request_id=%s, document_id=%s", request_id, document_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        for path in (temp_path, direct_temp_path):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except Exception as cleanup_exc:
                log.warning("Failed to remove temporary upload, request_id=%s: %s", request_id, cleanup_exc)
        if garage_key and not completed:
            try:
                from app.garage_client import delete_garage_object

                delete_garage_object(garage_key)
            except Exception as cleanup_exc:
                log.warning(
                    "Failed to cleanup staging PDF after ingest failure, request_id=%s: %s",
                    request_id,
                    cleanup_exc,
                )
