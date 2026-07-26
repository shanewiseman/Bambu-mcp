# Testing and verification

## Automated layers

- Unit tests: strict schemas, canonical digests, credential encryption/redaction,
  paths, artifact hashing, STL/3MF inspection, sparse state, X2D routing,
  operation gates, state transitions, approval expiry/replay, and recovery.
- Protocol contracts: MQTT QoS/sequence/duplicate/stale/timeout/disconnect,
  verified TLS, implicit FTPS names/failures, simulated status/commands/files,
  slicer readiness/dual failures, and RTSPS input safety.
- Service contracts: registry, preflight failures, single/dual/material routes,
  guarded actions, audit events, queue/monitor/pause/cancel/archive, and restart.
- HTTP/MCP: auth, upload/download/approval, health/readiness, OpenAPI surface,
  stdio/Streamable HTTP initialization, tool/resource schemas, and generated
  reference freshness.
- End to end: STL upload → inspect → X2D slice → validate → plan → approve →
  mock FTPS upload → correlated MQTT start → RUNNING.

JenkinsService runs the digest-pinned Python 3.12.11
`.jenkins/pipeline.yaml` contract with exact Python dependency locks.
Repository gates cover Ruff, strict mypy, Python compilation, Bandit, pytest
branch coverage, pip-audit, wheel/sdist and packaged migrations, generated-doc
diff, runtime-only CycloneDX SBOM, and license policy. Separate exact
development and runtime environments keep test/build tooling out of release
inventory evidence. JenkinsService adds its mandatory Gitleaks and Trivy gates
and isolates every step from the network except the declared dependency
bootstrap and vulnerability audit.

The Jenkins repository runtime intentionally receives no Docker daemon
credentials. Run `docker compose config`, the core image build, and the disposable
`container-test` target in the trusted container-validation workflow.
That target reruns the complete simulated STL-to-archived-job path against the
installed runtime wheel and is not part of the final image. The full AGPL Studio
source build is manual because it is resource intensive. Hardware is manual-only.

## Local commands

Use the validation block in the README. `scripts/validate-native.sh` is fully
hardware-free and offline after `scripts/ci-bootstrap.sh`; run
`scripts/audit-dependencies.sh` separately when vulnerability-service egress is
available. Coverage is a release gate, not a target to game: exempt only
unreachable typing/main guards; exercise failure branches. Golden archives are
tiny generated fixtures with no third-party model/profile assets.

## Hardware tests

Hardware tests require an explicit environment marker, fixture serial, operator
presence, pre-test backup/evidence directory, and the stages in
`hardware-validation.md`. They must default to read-only and must never run on
ordinary pull requests. A passed simulator test changes no protocol evidence
label.
