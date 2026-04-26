FROM public.ecr.aws/lambda/python:3.12

WORKDIR /var/task

# Get uv from the official image — used for lock-file-based dependency export
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Improve cold-start performance and create deterministic layers
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_INSTALLER_METADATA=1
ENV UV_LINK_MODE=copy

# Install third-party dependencies into Lambda task root.
# --target installs flat into /var/task, which Lambda adds to PYTHONPATH.
# --no-emit-workspace excludes the local 'analyzer' package (copied separately below).
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-emit-workspace --no-dev -o /tmp/requirements.txt && \
    uv pip install -r /tmp/requirements.txt --target "${LAMBDA_TASK_ROOT}"

# Copy application source — Lambda needs PYTHONPATH to include /var/task/src
COPY src/ ./src/
ENV PYTHONPATH="${LAMBDA_TASK_ROOT}/src:${LAMBDA_TASK_ROOT}"

# Lambda handler — set CMD per function in the Lambda console or deploy script:
#   analyzer-pipeline: CMD = ["analyzer.pipeline.lambda_handlers.pipeline_handler"]
#   analyzer-morning:  CMD = ["analyzer.pipeline.lambda_handlers.morning_handler"]
#   analyzer-api:      CMD = ["analyzer.api.app.handler"]
CMD ["analyzer.api.app.handler"]
