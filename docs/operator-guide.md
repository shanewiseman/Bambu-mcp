# Operator guide

## Prepare the environment

Use a dedicated Linux host or VM with Docker Compose, reliable time, encrypted
disk, and a trusted printer VLAN. Enable Developer Mode at the printer according
to the firmware UI and record the printer's literal IP, serial, model, firmware,
and LAN access code. Bambu states that Developer Mode exposes unsupported local
MQTT, file, and streaming integrations; treat the printer LAN as a security
boundary.

Generate secrets with `bambu-mcp keygen credential` and `bambu-mcp keygen api`
or retrieve them from a secret manager. Export them as
`BAMBU_MCP_CREDENTIAL_KEY` and `BAMBU_MCP_API_KEY` only in the secure shell that
runs Compose. Compose 2.23.1 or newer materializes mode-0400 secret files owned
by the non-root core UID; the values do not enter the container environment.
Store both values separately for recreation and recovery, then clear the shell
when deployment finishes. Never reuse a printer access code as an API key.

## Profiles and slicing

Export or otherwise obtain full Bambu Studio machine, process, and filament JSON
profiles that are compatible with Studio 2.7.1.62. Store them as:

- `profiles/machine/<printer_profile>.json`
- `profiles/process/<process_profile>.json`
- `profiles/filament/<filament_profile>.json`

Names passed through MCP are file stems and cannot contain path separators.
Profile redistribution rights are the operator's responsibility. Keep a
pre-sliced, verified `.gcode.3mf` path available because dual-nozzle CLI slicing
is a release gate, not an assumed capability.

## First deployment

1. Leave `ALLOW_UNVERIFIED_X2D_WRITES` and experimental tools false.
2. Run `docker compose config` and inspect networks, secrets, mounts, and the
   loopback port before `docker compose up`.
3. Require `/healthz` and `/readyz` to succeed. Readiness includes the exact
   Studio sidecar version and smoke result.
4. Register one printer through MCP. The returned object never contains the
   access code.
5. Run capability discovery and read status, nozzle, AMS/FTS, HMS, files, and a
   camera snapshot. Compare them with the printer screen.
6. Upload a small known STL, prepare a plan, and inspect every bound field. Do
   not enable writes merely to make an acceptance check pass.

## Normal print procedure

1. Upload/import and retain the SHA-256 ID.
2. Prepare the pipeline with explicit X2D profile, bed, plate, nozzle diameter,
   filament profiles, and every material route. Multi-material work without a
   complete route is rejected.
3. Confirm idle state, no HMS faults, selected plate, dimensions, slice hash,
   model/firmware, profile versions, nozzle/AMS mapping, FTS status, estimated
   metadata, and calibration options.
4. Call `approve_print_plan`; tokens should be handled like short-lived secrets.
5. Execute within ten minutes. Upload and start each require positive evidence;
   a missing acknowledgement fails the job.
6. Monitor to a terminal state. Clear the physical plate before queued work.

## Backups

Stop writes or stop the service. Copy `data/bambu-mcp.db` and the entire artifact
volume together, record SHA-256 hashes and service version, and encrypt the
backup. Store the credential key in a separate secrets backup. A restore test
must verify database integrity, artifact hashes, credential decryption using a
test record, and a simulated workflow; never use restore testing to start a
physical print.

## Upgrades

Read the changelog and protocol matrix diff. Back up first. Build both images,
run CI/contract tests, and confirm the Studio source tag/commit. Apply Alembic
migrations once. Start with writes disabled, compare read-only capability/status
snapshots, and re-enable only after review. Firmware upgrades are performed
outside this product and trigger a new capability/evidence review.
