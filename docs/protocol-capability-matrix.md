# Protocol capability matrix

Last reviewed: 2026-07-25. This is a provenance and safety artifact, not an
official Bambu Lab API specification. “Catalogued” means the concept is retained
for investigation; it does not mean writes are enabled. Firmware applicability
is unknown unless a range is explicitly evidenced.

Evidence levels: **official** (vendor product/tool documentation),
**community-observed** (published reverse engineering), **simulated** (this
repository's contract behavior), **captured** (redacted network capture), and
**hardware-verified** (command plus physical observation and restore evidence).
No row is captured or hardware-verified in this release.

Sources:

- [Bambu Lab X2D product article](https://blog.bambulab.com/xcellence-made-simple-bambu-lab-presents-the-x2d/), published 2026-04-14, accessed 2026-07-25 (`X2D`).
- [Bambu Studio 2.7.1.62 release](https://github.com/bambulab/BambuStudio/releases/tag/v02.07.01.62), published 2026-06-16, accessed 2026-07-25 (`Studio release`).
- [Bambu Studio CLI](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage), updated 2026-03-31, accessed 2026-07-25 (`Studio CLI`).
- [OpenBambuAPI MQTT](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md), [FTPS](https://github.com/Doridian/OpenBambuAPI/blob/main/ftp.md), and [TLS](https://github.com/Doridian/OpenBambuAPI/blob/main/tls.md), accessed 2026-07-25 (`OpenBambu`).
- [Bambuddy public behavior](https://github.com/maziggy/bambuddy), accessed 2026-07-25 (`Bambuddy`). Only public README/release behavior was consulted, not source.
- [Bambu Lab security white paper](https://cdn1.bambulab.com/trust-center/file/bambulab-security-whitepaper-en.pdf), version 2025.09, accessed 2026-07-25 (`White paper`).

| Family / operation | Topic / transport and fields | Model / firmware | Source / date | Risk | Implementation | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| LAN authentication | MQTT 8883 TLS; username `bblp`; Developer Mode access code | Community describes X/P/A; X2D assumed, firmware unknown | OpenBambu / 2026-07-25; White paper / 2026-07-25 | read-only boundary | Implemented with encrypted credential; X2D connection unverified | community-observed + simulated |
| MQTT request | `device/{serial}/request`; JSON family object, `sequence_id`, `command`, parameters; QoS 1 | Published general behavior; X2D unknown | OpenBambu / 2026-07-25 | varies | Exact topic only; monotonic sequence; QoS 1 | community-observed + simulated |
| MQTT report | `device/{serial}/report`; `sequence_id`, `command`, case-insensitive `result`, optional `reason` | Published general behavior; X2D unknown | OpenBambu / 2026-07-25 | read-only | Exact topic; ack correlation; duplicate suppression | community-observed + simulated |
| Sparse status reports | Recursive object updates; arrays/scalars authoritative | P1 sparse, X1 full; X2D unknown | OpenBambu / 2026-07-25 | read-only | Deep merge with caller-data isolation | community-observed + simulated |
| TLS trust | Bambu CA chain; TLS >=1.2; LAN cert hostname/IP mismatch documented | LAN printers; Python strict-mode caveat | OpenBambu / 2026-07-25 | security boundary | CA required, no insecure mode; hostname disabled with limitation documented | community-observed + simulated |
| `info.get_version` | Request `info:{sequence_id,command}`; report `module[]` with `name`, `sw_ver`, `hw_ver`, `sn` | General; X2D unverified | OpenBambu / 2026-07-25 | read-only | Tool, discovery snapshot, serial redaction through state policy | community-observed + simulated |
| `pushing.pushall` | `version:1`, `push_target:1`; full status response | General; P1 rate caution; X2D unverified | OpenBambu / 2026-07-25 | read-only | Tool-internal status refresh | community-observed + simulated |
| `print.push_status` | `gcode_state`, progress/layers, temperatures, fans, HMS, AMS, camera, lights, SD, errors, Wi-Fi and sparse fields | Examples are older models; X2D fields incomplete | OpenBambu / 2026-07-25 | read-only | Resources and typed projections; unknown fields retained | community-observed + simulated |
| `mc_print.push_info` | `param` log line; pressure-advance/humidity examples | General unknown | OpenBambu / 2026-07-25 | read-only/sensitive | Catalogued in matrix only; no log resource | community-observed |
| `print.pause` | `param:""`; correlated result | General; X2D unverified | OpenBambu / 2026-07-25 | routine mutation | Typed tool and durable pause workflow | community-observed + simulated |
| `print.resume` | `param:""`; correlated result | General; X2D unverified | OpenBambu / 2026-07-25 | routine mutation | Typed tool and durable resume workflow | community-observed + simulated |
| `print.stop` | `param:""`; correlated result | General; X2D unverified | OpenBambu / 2026-07-25 | guarded | Job/action approval, safe cancel, ack required | community-observed + simulated |
| `print.print_speed` | `param` string `1..4` | General; X2D unverified | OpenBambu / 2026-07-25 | routine mutation | Bounded typed tool | community-observed + simulated |
| `print.project_file` | local FTP URL, plate G-code `param`, task/profile IDs, calibration/timelapse, `ams_mapping`, `use_ams` | General payload; X2D extensions uncertain | OpenBambu / 2026-07-25 | guarded / print start | Only durable execute pipeline after upload/preflight/approval; ack required | community-observed + simulated |
| `ams_mapping` | Per-filament source array; published older mapping/padding behavior | AMS printers; X2D left semantics inferred | OpenBambu / 2026-07-25 | guarded plan field | Explicit left mapping, hash-bound, completeness validation | community-observed + simulated |
| `ams_mapping2` | Secondary per-filament source array | Dual-nozzle H2D/X2D observed at high level; field details uncertain | Bambuddy / 2026-07-25 | guarded plan field | X2D adapter output; no hardware claim | simulated |
| `nozzle_mapping` | Per-filament left/right values `0/1` | X2D/H2 dual nozzle; firmware unknown | X2D; Bambuddy / 2026-07-25 | guarded plan field | Explicit adapter output; no hardware claim | official concept + simulated field |
| External spool routing | Virtual tray sentinel 254 in older status; X2D has dual extrusion paths | General virtual tray; X2D routing uncertain | OpenBambu; X2D / 2026-07-25 | guarded plan field | One exclusive AMS/external source; sentinel 254 | community-observed + simulated |
| Filament Track Switch | Per-nozzle/source routing behavior; exact request fields unknown | X2D; Studio 2.7.1.62 includes X2D FTS UI fix | Studio release; Bambuddy / 2026-07-25 | guarded / uncertain | Read fields catalogued; all FTS routes fail closed without hardware verification | official feature association + simulated |
| `print.ams_change_filament` | `target`, `curr_temp`, `tar_temp` | AMS printers; dual-extruder meaning uncertain | OpenBambu / 2026-07-25 | guarded | Bounded load tool; unverified X2D gate | community-observed + simulated |
| `print.unload_filament` | command; older firmware may use system G-code file | Model/firmware variation unknown | OpenBambu / 2026-07-25 | guarded | Guarded tool; no fallback G-code-file exposure | community-observed + simulated |
| `print.ams_get_rfid` | published uses inconsistent `sequenceId`; `ams_id`, `slot_id` | AMS; firmware unknown | OpenBambu / 2026-07-25 | guarded | Guarded bounded refresh; standard envelope uses `sequence_id` | community-observed + simulated |
| `print.ams_user_setting` | `ams_id`, `startup_read_option`, `tray_read_option` | AMS; firmware unknown | OpenBambu / 2026-07-25 | guarded | Guarded bounded configuration | community-observed + simulated |
| `print.ams_filament_setting` | tray/profile/color/type/nozzle temperature range | AMS; firmware unknown | OpenBambu / 2026-07-25 | guarded | Catalogued; not a standalone tool in 0.1 | community-observed |
| `print.ams_control` | `param` pause/resume/reset | AMS; firmware unknown | OpenBambu / 2026-07-25 | guarded | Catalogued; not exposed in 0.1 | community-observed |
| AMS drying | AMS ID, temperature, duration; exact command/payload uncertain | AMS 2 Pro/HT observations; X2D attachment unknown | Bambuddy / 2026-07-25 | guarded / uncertain | Typed bounds, catalogued `ams_drying`, unverified gate; no hardware claim | simulated |
| `print.skip_objects` | `obj_list`, optional timestamp; report `s_obj` | Supporting printers/files | OpenBambu / 2026-07-25 | guarded | Positive unique IDs and exact action approval | community-observed + simulated |
| `print.calibration` | option bitmask bits 0..3; firmware may use system G-code file | Model/firmware variation unknown | OpenBambu / 2026-07-25 | guarded | Mask bounded to 0..15; exact approval | community-observed + simulated |
| `print.gcode_line` temperatures | G-code in `param` | General; per-tool X2D commands uncertain | OpenBambu / 2026-07-25 | guarded | Generated bounded bed/nozzle/chamber commands | community-observed transport + simulated commands |
| `print.gcode_line` fans | G-code in `param`; `M106` convention | General; X2D fan indices uncertain | OpenBambu status / 2026-07-25 | routine mutation | Percent/channel bounded; unverified X2D gate | simulated |
| `print.gcode_line` homing/jog | allowlisted `G28`, relative `G0`, restored absolute mode | General; motion envelope model-specific | OpenBambu transport / 2026-07-25 | guarded | Axis/distance/feedrate bounds and exact approval | simulated |
| `print.gcode_line` raw | arbitrary `param`, optional user ID | General | OpenBambu / 2026-07-25 | experimental high risk | Feature flag + exact approval + length/NUL limit | community-observed + simulated |
| `print.gcode_file` | absolute printer filesystem `param` | General; unsafe path semantics | OpenBambu / 2026-07-25 | high risk | Not exposed; project workflow only | community-observed |
| `print.print_option` | allowlisted detection/recovery/sound boolean fields | Model/firmware-specific | OpenBambu / 2026-07-25 | experimental | Feature flag, field allowlist, approval | community-observed + simulated |
| `xcam.xcam_control_set` | `module_name`, `control`, `print_halt` | Models with XCam; X2D unknown | OpenBambu / 2026-07-25 | experimental/guarded | Catalogued through detection options only; no direct module tool | community-observed |
| `system.ledctrl` | chamber/work node, on/off/flashing and timing fields | Two lights reported; X2D unverified | OpenBambu / 2026-07-25 | routine mutation | Exact node/mode and fixed timing | community-observed + simulated |
| `system.set_accessories` nozzle | accessory type, diameter/type | Supporting models; X2D dual semantics unknown | OpenBambu / 2026-07-25 | guarded | Catalogued; not exposed in 0.1 | community-observed |
| `system.get_access_code` | returns LAN credential | Supporting firmware | OpenBambu / 2026-07-25 | forbidden credential | Explicitly blocked, including raw mode | community-observed + simulated block |
| `camera.ipcam_record_set` | `control:enable|disable` | Camera models; X2D unverified | OpenBambu / 2026-07-25 | routine mutation | Typed tool and ack | community-observed + simulated |
| `camera.ipcam_timelapse` | `control:enable|disable` | Camera models; X2D unverified | OpenBambu / 2026-07-25 | routine mutation | Typed tool and ack | community-observed + simulated |
| RTSPS camera | TLS stream on port 322; access-code auth; exact path `streaming/live/1` | Community behavior; X2D path unverified | Bambuddy behavior / 2026-07-25 | read-only / credential-bearing | Literal IP, percent-encoded credential userinfo, argument-safe ffmpeg in default private container PID namespace; trusted host argv exposure documented, artifact snapshot | community-observed + simulated input safety |
| Implicit FTPS | TLS immediately on 990; `bblp`/access code; protected data | General; X2D unverified | OpenBambu / 2026-07-25 | read/write | List/upload/delete basename only; size verify; approvals on writes | community-observed + simulated |
| Firmware `upgrade_confirm` | `upgrade` family, `src_id`; result unpublished | Model/firmware-specific | OpenBambu / 2026-07-25 | forbidden | Not exposed; raw block | community-observed catalog |
| Firmware `consistency_confirm` | `upgrade` family, `src_id`; result unpublished | Model/firmware-specific | OpenBambu / 2026-07-25 | forbidden | Not exposed; raw block | community-observed catalog |
| Firmware `start` | URL, module, version, `src_id` | Model/firmware-specific | OpenBambu / 2026-07-25 | forbidden | Not exposed; raw block | community-observed catalog |
| Firmware `get_history` / downgrade | firmware/module history; downgrade unpublished | Model/firmware-specific | OpenBambu / 2026-07-25 | forbidden | Not exposed | community-observed catalog |
| X2D dual extrusion | mechanically switched left direct/right auxiliary systems | X2D product generation | X2D / 2026-07-25 | plan/safety boundary | Two nozzles/tools represented; physical switching not commanded directly | official + simulated |
| X2D chamber heat | chamber up to 65°C; exact LAN family/fields unknown | X2D | X2D / 2026-07-25 | guarded / uncertain | 0..80 schema permits investigation; catalogued command blocked by evidence gate | official concept + simulated field |
| X2D airducts | cooling/heating modes; exact LAN family/fields unknown | X2D | X2D / 2026-07-25 | guarded / uncertain | Bounded catalogued operation; no support claim | official concept + simulated field |
| X2D active extruder | left/right selection; exact LAN family/fields unknown | X2D | X2D / 2026-07-25 | guarded / uncertain | Bounded catalogued operation; no support claim | official concept + simulated field |
| Pressure advance profiles | published push log observations; write family uncertain | Model/firmware-specific | OpenBambu / 2026-07-25 | experimental | Feature flag + approval; catalogued command only | community-observed report + simulated write |
| Raw MQTT | same fixed request topic; caller family/command/parameters | Unknown | Community protocol envelope / 2026-07-25 | experimental high risk | Feature flag + approval; upgrade/access-code blocked; no arbitrary topic | simulated |
| Bambu Studio slice | `--load-settings`, `--load-filaments`, `--slice`, `--export-3mf`, explicit input | Studio 2.7.1.62; X2D profiles operator-supplied | Studio CLI/release / 2026-07-25 | isolated artifact transform | Sidecar implemented; exact version; dual-nozzle smoke gate | official CLI + simulated contract |
| `.gcode.3mf` validation | ZIP content types/model XML and `Metadata/*.gcode`; estimates/profile metadata varies | General Studio output | Studio CLI; community behavior / 2026-07-25 | pre-upload safety | Hardened, no extraction, hash-bound; model/profile semantic coverage partial | simulated |

## Deliberate exclusions

Cloud endpoints, MakerWorld, firmware changes, access-code retrieval or update,
arbitrary MQTT topics, opaque network bridges, and arbitrary printer/host paths
are outside the service. An exclusion cannot be bypassed by enabling experimental
tools.
