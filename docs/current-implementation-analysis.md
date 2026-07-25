# Current implementation analysis

## Frozen capability baseline

The implementation plan records that the pre-existing GPL-2.0 TypeScript fork
exposed 41 MCP tools, three resources, MQTT/FTPS connectivity, 3MF inspection,
AMS mapping, STL transforms, slicing, camera snapshots, and print controls. That
summary is a behavioral baseline only. Its source was not copied, translated,
imported, or consulted while implementing this Python core.

The baseline's recorded gaps were no X2D support, incomplete protocol coverage,
synchronous operations, weak acknowledgement tracking, unrestricted low-level
network calls, and no durable multi-printer workflow engine. Cloud APIs,
firmware updates, access-code retrieval, MakerWorld, and opaque bridges were
explicitly excluded.

## What this repository implements

- 56 typed MCP tools and resources spanning registration/read state, artifacts,
  model handling, X2D material/nozzle mapping, routine controls, guarded
  operations, and persistent print workflows.
- Async MQTT command correlation, QoS 1, sparse deep merge, duplicate handling,
  disconnect failure, exact topics, pinned-CA TLS, and implicit FTPS basenames.
- SQL records for multiple printers, encrypted credentials, capabilities,
  artifacts, jobs, steps, approvals, and redacted audit events.
- Content-addressed uploads and constrained imports rather than arbitrary paths.
- X2D/N6 dual-nozzle concepts and explicit FTS/chamber/airduct uncertainty.
- A separated Studio sidecar, complete CLI inputs, safe output validation,
  dual-nozzle smoke gate, and pre-sliced fallback.
- Durable prepare/approve/execute, queue, monitor, pause/diagnose, resume, safe
  cancel, material preflight, skip/calibrate/file action primitives, and archive.
- Narrow HTTP, generated OpenAPI/MCP references, containers, migrations, CI,
  consumer/operator/security/protocol documentation, and test contracts.

## Honest limitations

There is no physical X2D evidence, complete official LAN protocol, role-based
authorization, cloud service, distributed database/worker coordination, or
validated public license. Some X2D request families are catalogued but blocked.
The sidecar source build and hardware suites are operational release gates. The
project is suitable for review and simulated evaluation; publication of a
production/hardware-support claim is not.
