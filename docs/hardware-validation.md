# Staged X2D hardware validation

No X2D was available for the initial implementation. This procedure is a manual
release gate, not an automated claim.

## Preconditions

- Named operator and observer; exact printer serial/model/firmware and probe host.
- Isolated trusted LAN, stable power, empty safe build volume, fire controls, and
  physical emergency access.
- Encrypted evidence directory with raw captures excluded from Git; redaction
  plan for access code, serial, IP, SSID, filenames, tokens, and camera imagery.
- Database/artifact backup with hashes and a tested restore path.
- Exact core/image/profile commits, dependency lock/SBOM, capability matrix
  baseline, and unverified writes disabled.

## Stages

1. **Read-only capture:** connect with Developer Mode, version/status/AMS/FTS/HMS/
   files/camera only. Compare sparse merge and capability snapshot to the screen.
2. **Low-energy controls:** enable the named write gate, exercise chamber and
   work lights, then restore original state. Record command, sequence, ack,
   observed state, and restore evidence.
3. **Existing print pause/resume:** use a harmless pre-existing print selected by
   the operator. Verify correlated acknowledgements and screen state. Do not
   start a new print.
4. **Upload without start:** upload a known tiny `.gcode.3mf`, verify size/hash or
   best available evidence, list it, then approval-delete it. Confirm no start.
5. **Single-nozzle print:** prepare/approve a small low-temperature known model,
   verify all plan fields, observe start/monitor/completion, and retain artifact,
   MQTT, FTPS, and operator evidence.
6. **Dual-nozzle and FTS:** only after prior stages. Test each mapping combination
   separately, then chamber/airduct and calibration families if safely scoped.

Stop immediately on unexpected motion/heating/tool selection, missing or
mismatched acknowledgement, state disagreement, firmware prompt, HMS fault, or
network ambiguity. Restore the physical state and configuration after every
stage.

## Evidence promotion

A matrix row becomes `hardware-verified` only with redacted capture ID, exact
firmware/model, command/request/result, physical observation, restore evidence,
and reviewer sign-off. Firmware ranges cannot be inferred from one version.
Failures and unknowns remain in the matrix. Record backup hash and restore result
in the validation report; never claim restoration without performing it.
