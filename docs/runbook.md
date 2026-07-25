# Operations runbook

## Health and readiness

- `/healthz`: core process, database query, and writable artifact root.
- `/readyz`: health plus exact slicer version/smoke. A 503 means pre-sliced
  ingestion may still be diagnosable, but the deployment is not ready for its
  advertised full workflow.

Use `docker compose ps`, then inspect redacted logs for the failing component.
Never print environment variables or mounted secret contents during diagnosis.

## Common failures

### MQTT timeout or disconnect

Do not retry the mutation automatically. Check printer power, IP, serial,
Developer Mode, VLAN rules, system time, CA bundle, and printer screen. Pending
acknowledgements fail on disconnect. Reconcile live status and job events before
creating a new action and approval.

### FTPS upload mismatch

The job fails before start. Confirm port 990/data policy, free printer storage,
filename, and access code. List files read-only. Delete a partial file only with
a new exact approval.

### Slicer not ready

Confirm source commit/version, binary `--help`, profile mounts, artifact volume
ownership, tmpfs capacity, and dual-smoke flag. The fresh artifact volume must be
setgid GID 10000 (directories 2770, files 0640) so core UID 10001 and slicer UID
10002 can exchange work. Quiesce and hash-back up an older volume before an
administrator repairs ownership; never recursively chmod a live artifact store.
Use a known pre-sliced archive; do not change the profile to make slicing pass.

### Approval rejected

Expected causes are expiration, replay, wrong job, job-state change, parameter
change, firmware change, or modified plan. Render a fresh plan/action for human
review. Tokens cannot be extended or reset.

### Restart during a job

`UPLOADING` and `STARTING` become `FAILED` because their side effects are
ambiguous. Inspect printer storage and screen. `RUNNING` remains monitorable and
can reconcile to paused/succeeded/failed. Never edit SQLite state manually.

## Backup and restore

Quiesce the service. Back up database and artifact volume together and record
hashes; back up credential key separately. For restore, use a new isolated host,
verify file hashes and SQLite `PRAGMA integrity_check`, confirm the restored
SQLite file is mode `0600`, confirm every referenced artifact exists and hashes
correctly, then run simulated tests with printer network blocked. Restore is not
proven until those results are recorded.

## Credential loss or compromise

A lost credential key cannot decrypt records; re-register printer credentials.
For compromise, stop the core, rotate printer access codes at each printer,
generate new application secrets, rebuild records, and review audit/network
evidence. There is intentionally no MCP credential-manipulation tool.

## Safe shutdown

Pause/stop physical work using the printer UI when immediate safety matters.
After reconciliation, stop Compose normally. Avoid force-killing SQLite during
writes. Preserve the database and redacted logs for failed or ambiguous jobs.
