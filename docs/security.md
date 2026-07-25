# Security model and deployment guide

## Threat model

Bambu MCP assumes the host, Docker daemon, mounted secrets, and a dedicated
printer LAN are administered by a trusted operator. It does not trust MCP/HTTP
inputs, uploaded archives, filenames, profile names, printer reports, network
availability, or protocol acknowledgements. A compromised printer or another
host able to present a Bambu-CA certificate remains a material threat because
current LAN certificates do not identify printer IP addresses.

Primary risks are unintended physical motion/heating, starting the wrong slice,
credential disclosure, archive/path attacks, MQTT spoofing/replay, ambiguous
retries after restart, sidecar compromise, and an AI client exceeding operator
intent.

## Controls

- Loopback bind by default; non-loopback configuration is rejected without an
  API key. Compose publishes only `127.0.0.1:8000`.
- Constant-time bearer/API-key comparison. Health endpoints disclose only
  component booleans; every other HTTP/MCP path requires the key when configured.
- Printer access codes are Fernet-encrypted with an external Docker secret.
  Sensitive keys and inline secret forms are recursively redacted from audit and
  returned state.
- MQTT publishes only `device/<serial>/request`, subscribes only to the matching
  report topic, uses QoS 1, monotonically increasing sequence IDs, correlated
  results, bounded waits, and duplicate-delivery suppression.
- TLS requires certificate-chain validation against the pinned Bambu CA bundle
  and TLS 1.2+. Hostname checks are disabled only because printer certificates
  do not identify LAN IP addresses; blanket insecure TLS is never enabled.
- FTPS wraps the control connection immediately on port 990, protects data
  connections, and accepts only a remote basename. Upload size is checked.
- Local imports are off by default and resolve through a strict `/imports`
  allowlist. MCP tools use artifact IDs, never host paths.
- ZIP/XML limits and no-extraction parsing mitigate traversal, entity expansion,
  symlinks, and decompression bombs.
- All mutations pass the X2D hardware-evidence gate. Consequential operations
  additionally require exact, expiring, one-use approval; experimental tools
  need a separate feature flag.
- Firmware upgrade and credential retrieval/manipulation are forbidden even in
  raw mode. Raw MQTT cannot choose a topic.
- Containers run as non-root without Linux capabilities and with
  `no-new-privileges`. The core has no PID namespace sharing override, so
  Docker uses its private default and sibling containers cannot inspect its
  process arguments unless deliberately joined to that namespace. The slicer
  root filesystem is read-only. Compose must
  materialize environment-sourced secrets before the core starts, so the core
  root filesystem is not mounted read-only; all image paths are root-owned and
  non-writable to UID 10001, leaving only explicit tmpfs and data/artifact
  volumes writable. The slicer has only an internal network and read-only
  profiles; it cannot route to the printer LAN.

## Operator requirements

1. Place the host and printers on a protected VLAN. Permit core-to-printer ports
   8883/TCP (MQTT), 990/TCP plus negotiated FTPS data flow, and 322/TCP (RTSPS)
   only as required. Do not allow slicer egress.
2. Terminate TLS and authentication at a trusted reverse proxy if remote access
   is unavoidable. Preserve bearer headers and enforce an origin/identity policy.
3. Keep the source values for `BAMBU_MCP_API_KEY` and
   `BAMBU_MCP_CREDENTIAL_KEY` in a secret manager. Export them only while Compose
   creates UID-owned, mode-0400 mounts; do not persist them in `.env` or shell
   history. Rotate the API key normally. Credential-key rotation requires a
   decrypt/re-encrypt migration and is not automated in this alpha.
4. Leave unverified X2D writes and experimental tools false. Temporarily enable
   them only for a named staged validation, with an operator at the printer.
5. Back up SQLite and the artifact tree as one consistency set. Back up the
   credential key separately. The core enforces owner-only mode `0600` on the
   SQLite file at schema initialization; preserve that mode during backup and
   restore. A database without matching artifacts or key is incomplete.
6. Review audit events and protocol-matrix changes before upgrades. Firmware can
   invalidate community-observed behavior.

## Known limitations

- The service has no user/role model; the API key is an operator-equivalent
  capability. Place per-user authorization at a gateway if needed.
- Fernet protects at-rest values, not a compromised running process.
- Camera capture necessarily places the percent-encoded access code in the
  ffmpeg RTSPS input argument. The default private container PID namespace
  limits visibility from sibling containers, but trusted host and Docker
  administrators can still observe it. Do not use snapshots from a bare-metal
  service or an untrusted multi-user host; rotate the printer access code after
  suspected process observation.
- The Bambu CA authenticates membership in the vendor PKI, not the expected
  printer identity. Network segmentation is therefore mandatory.
- Paho reconnect is fail-closed for pending commands; automated connection
  backoff and multi-process coordination are not release claims.
- Physical X2D behavior has not been validated. The `hardware_verified` database
  flag is not exposed as a general tool and must only be set through the manual
  evidence procedure.
- Bambu Studio and profiles process complex input. Sidecar isolation reduces but
  does not eliminate supply-chain and parser risk.

## Incident response

Stop the service, isolate printers, preserve redacted logs/SQLite/artifacts, and
rotate the API key after suspected unauthorized access. Rotate LAN access codes
from the printer UI and re-register records after suspected credential exposure.
Do not publish raw captures. For ambiguous in-flight jobs, inspect the printer
screen and SD card; never replay an approval or force a database state forward.
Follow the recovery procedures in the [runbook](runbook.md).
