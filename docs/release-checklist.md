# Release checklist

A release candidate is not publishable until every applicable item has recorded
evidence.

- [ ] Clean-room provenance/legal review approves the core license, Bambu CA,
  trademarks, profiles, and Studio sidecar distribution/corresponding source.
- [ ] `LICENSE.md`, notices, package metadata, image labels, and SBOM agree.
- [ ] Ruff, format, strict mypy, pytest branch coverage, Bandit, pip-audit,
  package build, migrations, generated references, Compose config, core image,
  and license/SBOM jobs pass from a clean checkout.
- [ ] Studio source tag resolves to the recorded commit; full build and single/
  dual-nozzle smoke evidence are retained, or the release documents pre-sliced
  only operation with automatic dual slicing disabled.
- [ ] Protocol matrix source dates, firmware ranges, risk, state, and evidence
  are current; no simulated observation is labelled captured/hardware-verified.
- [ ] Secrets/captures/profiles/private identifiers are absent from Git history.
- [ ] Backup and restore are performed with database/artifact/key hash evidence.
- [ ] Upgrade/rollback and ambiguous-job recovery are exercised.
- [ ] Physical hardware stages are recorded for every advertised write claim;
  unavailable fixtures remain explicit limitations.
- [ ] README, OpenAPI, MCP tool reference, operator/runbook/security guides,
  changelog, version/tag, and compatibility statements agree.
