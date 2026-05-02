"""ECS Fargate entry point for the pipeline batch tasks.

Replaces the Lambda handler dispatch. ECS does not receive an event payload —
instead the PIPELINE_JOB environment variable tells us which batch to run.

Task definition sets:
    PIPELINE_JOB=4pm      → analyzer-pipeline (4:30 PM IST)
    PIPELINE_JOB=morning  → analyzer-morning  (8:00 AM IST)

The existing Lambda handlers are reused directly — they are plain Python functions
that happen to accept (event, context). ECS passes an empty dict and None.
"""

from __future__ import annotations

import os
import sys

import structlog

from analyzer.utils.logging import configure_logging

configure_logging()
log = structlog.get_logger()


def main() -> None:
    job = os.getenv("PIPELINE_JOB", "").lower().strip()
    if not job:
        log.error("entrypoint_missing_env", var="PIPELINE_JOB", hint="Set to '4pm' or 'morning'")
        sys.exit(1)

    if job == "4pm":
        from analyzer.pipeline.lambda_handlers import pipeline_handler

        log.info("entrypoint_starting", job="4pm")
        result = pipeline_handler({}, None)
        log.info("entrypoint_done", job="4pm", result=result)

    elif job == "morning":
        from analyzer.pipeline.lambda_handlers import morning_handler

        log.info("entrypoint_starting", job="morning")
        result = morning_handler({}, None)
        log.info("entrypoint_done", job="morning", result=result)

    else:
        log.error("entrypoint_unknown_job", job=job, hint="PIPELINE_JOB must be '4pm' or 'morning'")
        sys.exit(1)


if __name__ == "__main__":
    main()
