# syntax=docker/dockerfile:1.7
# Bambu Studio is AGPL-3.0. This build obtains pinned corresponding source and
# keeps its artifacts outside the permissive Python wheel/core image.
FROM ubuntu:24.04 AS studio-builder
ARG DEBIAN_FRONTEND=noninteractive
ARG BAMBU_STUDIO_REF=v02.07.01.62
ARG BAMBU_STUDIO_COMMIT=42d319c6692fa8e64790fddf0cdaafd2a4254bcc
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates git sudo \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /source
RUN git clone --filter=blob:none --branch ${BAMBU_STUDIO_REF} \
      https://github.com/bambulab/BambuStudio.git . \
    && test "$(git rev-parse HEAD)" = "${BAMBU_STUDIO_COMMIT}" \
    && printf "%s\n" "${BAMBU_STUDIO_COMMIT}" > /BAMBU_STUDIO_COMMIT
RUN ./BuildLinux.sh -u
RUN ./BuildLinux.sh -1drsi
RUN image="$(find build -type f -name '*.AppImage' -print -quit)" \
    && test -n "${image}" \
    && chmod +x "${image}" \
    && "${image}" --appimage-extract \
    && mv squashfs-root /opt/bambu-studio

FROM python:3.12-slim-bookworm AS runtime
ARG BAMBU_STUDIO_COMMIT=42d319c6692fa8e64790fddf0cdaafd2a4254bcc
LABEL org.opencontainers.image.title="Bambu MCP Slicer Sidecar" \
      org.opencontainers.image.description="Isolated Bambu Studio slicing sidecar for Bambu MCP" \
      org.opencontainers.image.source="https://github.com/shanewiseman/Bambu-mcp" \
      org.opencontainers.image.version="2.7.1.62" \
      org.opencontainers.image.revision="${BAMBU_STUDIO_COMMIT}" \
      org.opencontainers.image.licenses="AGPL-3.0-only AND LicenseRef-Provenance-Review-Required"
ARG APP_UID=10002
ARG APP_GID=10002
ARG ARTIFACT_GID=10000
ENV BAMBU_STUDIO_VERSION=2.7.1.62 \
    BAMBU_STUDIO_BINARY=/opt/bambu-studio/AppRun \
    BAMBU_ARTIFACT_ROOT=/artifacts \
    BAMBU_PROFILE_ROOT=/profiles \
    BAMBU_SLICER_HOME=/tmp/bambu-slicer
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid ${ARTIFACT_GID} artifacts \
    && groupadd --gid ${APP_GID} slicer \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --groups artifacts \
         --create-home --home-dir /home/slicer slicer
COPY --from=studio-builder /opt/bambu-studio /opt/bambu-studio
COPY --from=studio-builder /BAMBU_STUDIO_COMMIT /opt/bambu-studio/SOURCE_COMMIT
WORKDIR /app
COPY pyproject.toml README.md LICENSE.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .
RUN install -d -o slicer -g artifacts -m 2770 /artifacts \
    && install -d -o root -g root -m 0555 /profiles \
    && install -d -o slicer -g slicer -m 0700 /tmp/bambu-slicer
USER slicer
EXPOSE 8080
ENTRYPOINT ["uvicorn", "bambu_mcp.slicer_sidecar:app", "--host", "0.0.0.0", "--port", "8080"]
