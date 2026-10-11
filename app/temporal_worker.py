from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from app.config import (
    TEMPORAL_HOST,
    TEMPORAL_NAMESPACE,
    TEMPORAL_PORT,
    TEMPORAL_TASK_QUEUE,
)
from app.temporal_activities import (
    generate_answer_activity,
    get_ingest_stats_activity,
    insert_document_activity,
    insert_images_activity,
    insert_nodes_activity,
    parse_pdf_activity,
    rebuild_index_activity,
    retrieve_activity,
)
from app.temporal_workflows import IngestWorkflow, QueryWorkflow

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# Temporal's workflow sandbox enforces determinism restrictions (e.g. no Path.resolve).
# Our app modules are imported inside the workflow sandbox during validation.
# We mark the entire "app" package as passthrough so the sandbox does not restrict
# module-level code like Path(__file__).resolve() in app/config.py.
_PASSTHROUGH_MODULES = SandboxRestrictions.default.with_passthrough_modules("app")


async def run_worker():
    """Run the Temporal worker to execute workflows and activities."""
    client = await Client.connect(
        f"{TEMPORAL_HOST}:{TEMPORAL_PORT}",
        namespace=TEMPORAL_NAMESPACE,
    )

    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[IngestWorkflow, QueryWorkflow],
        activities=[
            parse_pdf_activity,
            insert_document_activity,
            insert_images_activity,
            insert_nodes_activity,
            rebuild_index_activity,
            get_ingest_stats_activity,
            retrieve_activity,
            generate_answer_activity,
        ],
        workflow_runner=SandboxedWorkflowRunner(restrictions=_PASSTHROUGH_MODULES),
    )

    log.info(f"Worker started on task queue: {TEMPORAL_TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
