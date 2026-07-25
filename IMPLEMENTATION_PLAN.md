# X2D-First Python Bambu MCP Revamp

## Summary

Build the existing empty `Bambu-mcp` repository as an independently
implemented Python 3.12 service running through Docker Compose. The existing
GPL-2.0 TypeScript fork will serve only as a capability baseline; its source
will not be copied, translated, or imported.

The analysis will document that the existing fork provides 41 MCP tools, three
resources, MQTT/FTPS connectivity, 3MF inspection, AMS mapping, STL transforms,
slicing, camera snapshots, and print controls. Its primary gaps are lack of
X2D support, incomplete protocol coverage, synchronous operations, weak
acknowledgement tracking, unrestricted low-level network calls, and no durable
multi-printer workflow engine.

Implementation will be grounded in:

- Official [X2D product documentation][x2d], [Bambu Studio releases][studio-releases],
  [CLI documentation][studio-cli], and [Docker guide][studio-docker].
- Published community protocol research for [MQTT][openbambu-mqtt],
  [FTPS][openbambu-ftps], [TLS][openbambu-tls], camera streaming, and X2D
  behavior observed in [Bambuddy][bambuddy].
- The stable v1 [Python MCP SDK][python-mcp-sdk], pinned below the breaking v2
  release.

Cloud APIs, firmware updates, access-code retrieval, MakerWorld integration,
and legacy opaque network bridges will be documented but excluded from the
initial LAN-first implementation.

## Architecture and Public Interfaces

- Create an Apache-2.0 candidate Python core using `mcp>=1.27,<2`, Pydantic v2,
  FastAPI, SQLAlchemy/Alembic, Paho MQTT, `cryptography`, `trimesh`, and
  hardened XML/ZIP parsing.
- Run two non-root Compose services:
  - `bambu-mcp`: MCP over stdio and Streamable HTTP, artifact upload/download
    endpoints, persistent workflows, and printer connectivity.
  - `bambu-slicer`: pinned Bambu Studio 2.7.1.62 sidecar with shared artifact
    storage and no printer access.
- Keep the Bambu Studio sidecar and its build material under AGPL-3.0
  obligations, isolated from the permissive core. Require a provenance/legal
  review before publicly applying the Apache-2.0 license or distributing the
  composed image.
- Persist printers, encrypted credentials, capability snapshots, artifacts,
  jobs, steps, approvals, and audit events in SQLite. Supply encryption and API
  keys through Docker secrets.
- Store uploads by SHA-256 artifact ID. MCP tools accept artifact IDs rather
  than arbitrary host paths; optional local imports are restricted to a mounted
  `/imports` allowlist.
- Expose only:
  - `POST /api/v1/artifacts`, artifact metadata/download endpoints, approval
    submission, `/healthz`, and `/readyz`.
  - MCP Streamable HTTP at `/mcp`.
  - No general printer REST API.
- Provide MCP resources for printer status, capabilities, AMS/FTS inventory,
  HMS faults, files, job state/events, artifact metadata, and the protocol
  capability matrix.

### Individual MCP Tools

Implement typed tools for:

- Registry and inspection: printer registration/listing, capability discovery,
  status/version, nozzle state, AMS inventory, Filament Track Switch state, HMS
  faults, files, and camera snapshots.
- Artifacts and slicing: upload/import metadata, model
  inspection/repair/transform, 3MF inspection, slicing, material/nozzle mapping,
  and artifact download.
- Routine controls: pause/resume, speed, lights, fans, camera recording, and
  timelapse.
- Guarded controls: cancel/stop, skip objects, temperatures, chamber/airduct
  settings, extruder selection, homing/jogging, filament load/unload, AMS
  configuration/RFID/drying, calibration, file upload/delete, and print start.
- Experimental catalogued operations: pressure-advance profiles,
  detection/print options, raw G-code, and raw MQTT. These remain
  feature-flagged and approval-gated until verified on X2D hardware.

Firmware upgrade, credential manipulation, and arbitrary MQTT topics will
never be exposed as general tools.

## Protocol, X2D, and Workflow Implementation

- Maintain `docs/protocol-capability-matrix.md` with every published
  request/report family, topic, field set, model/firmware applicability, source
  URL/date, risk tier, implementation state, and evidence level: official,
  community-observed, simulated, captured, or hardware-verified.
- Use verified TLS against the Bambu CA, implicit FTPS on port 990, MQTT QoS 1,
  per-command sequence IDs, acknowledgement/result correlation, reconnect
  recovery, sparse-state deep merging, and credential/log redaction.
- Add an X2D/N6 model adapter covering dual nozzles, active tool,
  `ams_mapping`, `ams_mapping2`, `nozzle_mapping`, external spool/FTS routing,
  chamber heating, airducts, two lights, RTSPS camera behavior, calibration
  flags, and firmware capability ranges.
- Catalog X2D FTS and dual-nozzle commands even when uncertain, but fail closed
  on writes until captured or hardware-verified.
- Pin and smoke-test the slicer sidecar at startup. Accept STL/3MF artifacts
  plus explicit X2D printer, bed, process, nozzle, filament, support,
  orientation, copy, and plate settings. Produce and validate `.gcode.3mf`
  artifacts.
- Validate target model, bed/nozzle profiles, object IDs, filament/nozzle
  mappings, archive integrity, and estimated material/time before printer
  upload. If dual-nozzle slicing fails its smoke test, retain the pre-sliced
  `.gcode.3mf` workflow and reject automatic dual-nozzle slicing.
- Implement durable jobs with the state sequence:
  `CREATED → INGESTED → INSPECTED → SLICED → VALIDATED → PREFLIGHTED → AWAITING_APPROVAL → UPLOADING → STARTING → RUNNING → PAUSED/SUCCEEDED/FAILED/CANCELLED`.
- Implement these multi-step tools:
  - `prepare_print_pipeline`: inspect, optionally repair/transform, slice,
    validate, resolve AMS/nozzles/FTS, and preflight live printer state.
  - `approve_print_plan`: issue a one-use, ten-minute approval bound to the
    immutable plan digest.
  - `execute_print_pipeline`: recheck live state, upload, verify, issue the X2D
    `project_file` command, require acknowledgement, and begin monitoring.
  - `submit_stl_pipeline`: convenience entry point that prepares the print and
    stops at approval.
  - Material preflight, queueing, monitoring, pause-and-diagnose, safe
    cancellation, object skipping, calibration, and completed-job archival
    workflows.
- Bind approvals to artifact and slice hashes, printer/model/firmware,
  slicer/profile versions, plate, nozzle/AMS/FTS mappings, and calibration
  options. Any change invalidates the approval.
- Allow offline ingestion, inspection, slicing, and preflight without approval.
  Require approval for upload/start/delete, cancellation, heating, motion,
  filament movement, calibration, and raw commands.
- Until an X2D is physically validated, require
  `ALLOW_UNVERIFIED_X2D_WRITES=true` in addition to normal authorization for
  all printer mutations.

## Verification and Acceptance

- Unit-test schemas, state merging, MQTT sequencing/acknowledgements, TLS
  behavior, credential redaction, path restrictions, 3MF validation, X2D
  nozzle/AMS/FTS mappings, approval expiry/replay prevention, and job recovery.
- Add contract services for mocked MQTT, FTPS, RTSPS, and slicing. Cover
  disconnects, stale sessions, duplicate QoS deliveries, failed
  acknowledgements, wrong printer profiles, invalid archives, unmapped
  materials, missing Developer Mode, and service restarts.
- Add a Docker end-to-end test:
  `upload STL → inspect → slice for X2D → validate → generate plan → approve → mock FTPS upload → mock MQTT start acknowledgement → RUNNING`.
- Include golden cases for single nozzle, dual nozzle, AMS, external spool, FTS
  routing, invalid profiles, missing camera, and firmware capability
  mismatches.
- CI will run Ruff, type checking, pytest with coverage, security/dependency
  audits, license/SBOM checks, Docker builds, MCP stdio/HTTP tests, and slicer
  smoke tests. Hardware tests remain manually triggered.
- When the X2D arrives, run staged hardware validation: redacted read-only
  capture, capability comparison, lights, a pre-existing print pause/resume,
  upload without start, a small single-nozzle print, then dual-nozzle/FTS
  tests. Update the matrix only from recorded evidence.
- Acceptance requires generated MCP/OpenAPI references, current-implementation
  analysis, protocol provenance matrix, X2D and slicing guides,
  security/runbook documentation, restart-safe jobs, and no claim of hardware
  support beyond the recorded evidence level.

## Assumptions and Concerns

- X2D LAN Developer Mode is the primary target; cloud connectivity is deferred.
- The system supports multiple durable printer records even though only X2D is
  initially enabled.
- MCP plus a narrow artifact/approval HTTP API is the selected interface.
- Published MQTT information is reverse-engineered rather than a complete
  official API and may change with firmware.
- Bambu states that Developer Mode exposes local MQTT, file, and streaming
  services while those integrations remain unsupported; the container must
  stay on a trusted printer LAN and bind host-facing services to loopback by
  default.
- No X2D is currently available, so initial write support is simulated and
  explicitly marked unverified.
- Clean-room implementation requires a frozen behavioral specification and
  provenance ledger. Implementers must not translate or consult the old GPL
  source while writing the new core.
- Bambu Studio is AGPL-3.0 and dual-extruder CLI defects have existed; license
  review, version pinning, smoke tests, and a pre-sliced fallback are release
  gates.

[x2d]: https://blog.bambulab.com/xcellence-made-simple-bambu-lab-presents-the-x2d/
[studio-releases]: https://github.com/bambulab/BambuStudio/releases
[studio-cli]: https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
[studio-docker]: https://github.com/bambulab/BambuStudio/wiki/Docker-Run-Guide
[openbambu-mqtt]: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
[openbambu-ftps]: https://github.com/Doridian/OpenBambuAPI/blob/main/ftp.md
[openbambu-tls]: https://github.com/Doridian/OpenBambuAPI/blob/main/tls.md
[bambuddy]: https://github.com/maziggy/bambuddy
[python-mcp-sdk]: https://github.com/modelcontextprotocol/python-sdk
