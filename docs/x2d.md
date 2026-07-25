# X2D/N6 support guide

## Evidence boundary

Official X2D product material establishes a mechanically switched dual-nozzle
system, distinct direct/auxiliary extrusion paths, a heated chamber up to 65°C,
300°C nozzles, and different build envelopes for the main, auxiliary,
intersection, and union modes. It does not publish a complete LAN command
protocol. Protocol fields in this project are therefore labelled official,
community-observed, simulated, captured, or hardware-verified independently.

This initial release has no physical X2D evidence. `X2D` and internal family
`N6` are enabled for records and simulation, but every mutation requires the
operator's unverified-write feature gate. FTS, chamber, airduct, and active-tool
write families remain fail-closed where the matrix says catalogued/simulated.

## Adapter model

The capability snapshot describes:

- left/direct and right/auxiliary nozzles and active tool;
- `ams_mapping` for left, `ams_mapping2` for right, and `nozzle_mapping` values
  0/1 per sliced filament;
- external spool sentinel 254 and explicit per-filament source exclusivity;
- catalogued FTS channels, which cannot be used before hardware verification;
- chamber heating, airducts, chamber/work lights, RTSPS snapshots, and
  calibration flags;
- firmware-aware operation availability and a risk/evidence label per operation.

Every sliced filament index must appear exactly once for multi-material work.
Duplicate, missing, or both AMS/external sources are rejected. Mappings are part
of the approval digest.

## Model validation

Automatic slicing accepts only an X2D/N6 printer profile in this release. A
sliced archive is still checked before upload; being produced by Studio is not a
trust decision. The plan binds printer model and firmware. A firmware change
after approval makes execution fail.

## What is not claimed

- Correct physical FTS routing or dual-nozzle project-file payloads on any X2D.
- Hardware-safe chamber/airduct/extruder commands.
- Automatic dual-nozzle CLI slicing unless the pinned sidecar smoke passes.
- Support for union/intersection build-volume validation beyond profile choice.
- Cloud, MakerWorld, firmware-update, or access-code workflows.

Close claims one stage at a time using [hardware validation](hardware-validation.md)
and update the protocol matrix only from retained redacted evidence.
