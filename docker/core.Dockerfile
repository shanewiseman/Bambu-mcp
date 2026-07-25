# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml README.md LICENSE.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels .

FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="Bambu MCP" \
      org.opencontainers.image.description="LAN-first, safety-gated MCP service for Bambu Lab printers" \
      org.opencontainers.image.source="https://github.com/shanewiseman/Bambu-mcp" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="LicenseRef-Provenance-Review-Required"
ARG APP_UID=10001
ARG APP_GID=10001
ARG ARTIFACT_GID=10000
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid ${ARTIFACT_GID} artifacts \
    && groupadd --gid ${APP_GID} bambu \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --groups artifacts \
         --create-home --home-dir /home/bambu bambu \
    && chmod 0555 /home/bambu \
    && install -d -o bambu -g bambu -m 0750 /data \
    && install -d -o bambu -g artifacts -m 2770 /artifacts
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
WORKDIR /app
COPY alembic.ini ./
COPY docs ./docs
COPY certs ./certs
USER bambu
EXPOSE 8000
ENTRYPOINT ["bambu-mcp"]
CMD ["http"]

FROM runtime AS container-test
USER root
RUN python -m pip install --no-cache-dir "pytest>=8.4,<9" "pytest-asyncio>=1.0,<2"
COPY tests /tests
USER bambu
RUN python -m pytest -p no:cacheprovider -o asyncio_mode=auto -q \
    /tests/test_workflow_pipeline.py::test_end_to_end_pipeline_approval_upload_start_and_archive

FROM runtime AS final
