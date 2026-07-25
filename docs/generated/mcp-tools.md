# MCP tool reference

Generated from the typed server definitions. Do not edit by hand.

## `approve_guarded_action`

Issue a one-use token bound to one exact guarded action and parameter set.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |
| `operation` | `string` | yes |
| `parameters` | `object | null` | no |

## `approve_print_plan`

Issue a one-use ten-minute token bound to the immutable print plan digest.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |

## `archive_completed_job`

Return a portable completion record with artifact and event evidence.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |

## `cancel_print_job`

Safely stop and cancel a job using an exact one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |
| `approval_token` | `string` | yes |

## `capture_camera_snapshot`

Capture one RTSPS frame and return its immutable artifact metadata.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `configure_ams`

Configure AMS RFID read behavior.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `ams_id` | `integer` | yes |
| `startup_read` | `boolean` | yes |
| `insertion_read` | `boolean` | yes |
| `approval_token` | `string` | yes |

## `delete_printer_file`

Delete one printer basename over FTPS with a one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `filename` | `string` | yes |
| `job_id` | `string` | yes |
| `approval_token` | `string` | yes |

## `discover_printer_capabilities`

Read firmware and refresh the model/firmware capability snapshot.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `dry_ams_filament`

Request catalogued AMS drying; unverified X2D writes remain fail-closed.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `ams_id` | `integer` | yes |
| `celsius` | `integer` | yes |
| `minutes` | `integer` | yes |
| `approval_token` | `string` | yes |

## `execute_print_pipeline`

Re-preflight, upload, verify, start, require acknowledgement, and monitor.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |
| `approval_token` | `string` | yes |

## `get_ams_inventory`

Read AMS units, trays, and the external-spool virtual tray.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `get_artifact_download_url`

Return the authenticated HTTP download URL for an artifact.

| Parameter | Type | Required |
| --- | --- | --- |
| `artifact_id` | `string` | yes |

## `get_artifact_metadata`

Return immutable artifact metadata by SHA-256 ID.

| Parameter | Type | Required |
| --- | --- | --- |
| `artifact_id` | `string` | yes |

## `get_fts_state`

Read catalogued Filament Track Switch fields without enabling FTS writes.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `get_hms_faults`

Read current Health Management System faults.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `get_nozzle_state`

Read active tool, nozzle temperatures, diameters, and targets.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `get_printer_status`

Return the merged sparse status report with secrets redacted.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `get_printer_version`

Request module versions from the printer.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `home_axes`

Home an allowlisted axis set with a guarded approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `axes` | `string` | yes |
| `approval_token` | `string` | yes |

## `import_local_artifact`

Import a file only from the operator-mounted /imports allowlist.

| Parameter | Type | Required |
| --- | --- | --- |
| `path` | `string` | yes |

## `inspect_3mf`

Revalidate a 3MF archive and report its safe members.

| Parameter | Type | Required |
| --- | --- | --- |
| `artifact_id` | `string` | yes |

## `inspect_model`

Return hardened 3MF or geometric STL inspection results.

| Parameter | Type | Required |
| --- | --- | --- |
| `artifact_id` | `string` | yes |

## `jog_axis`

Jog one axis within bounded distance/feedrate limits.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `axis` | `string` | yes |
| `millimeters` | `number` | yes |
| `feedrate` | `integer` | yes |
| `approval_token` | `string` | yes |

## `list_print_queue`

List non-terminal durable jobs in submission order.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string | null` | no |

## `list_printer_files`

List printer storage over implicit FTPS.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `list_printers`

List registered printers without exposing credentials.

## `load_filament`

Load an AMS slot using bounded temperature and slot values.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `slot` | `integer` | yes |
| `target_temperature` | `integer` | yes |
| `approval_token` | `string` | yes |

## `monitor_print_job`

Merge live printer state into the durable job lifecycle.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |

## `pause_and_diagnose`

Pause a running job and return current HMS/print diagnostics.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |

## `pause_printer`

Pause the current print and require a correlated acknowledgement.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `prepare_print_pipeline`

Inspect, slice, validate, map material, live-preflight, then stop for approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `request` | `PreparePrintRequest` | yes |

## `read_ams_rfid`

Request an AMS RFID refresh with a guarded approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `ams_id` | `integer` | yes |
| `slot_id` | `integer` | yes |
| `approval_token` | `string` | yes |

## `register_printer`

Register an X2D/N6 printer; its access code is encrypted at rest.

| Parameter | Type | Required |
| --- | --- | --- |
| `request` | `PrinterRegistration` | yes |

## `repair_model`

Create a conservatively repaired STL without changing its placement.

| Parameter | Type | Required |
| --- | --- | --- |
| `artifact_id` | `string` | yes |

## `resume_print_job`

Resume a durably paused job after acknowledgement.

| Parameter | Type | Required |
| --- | --- | --- |
| `job_id` | `string` | yes |

## `resume_printer`

Resume the current print and require a correlated acknowledgement.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |

## `run_calibration`

Run only documented calibration option bits 0-3.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `option_mask` | `integer` | yes |
| `approval_token` | `string` | yes |

## `select_extruder`

Select the X2D active extruder with a guarded approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `extruder` | `string` | yes |
| `approval_token` | `string` | yes |

## `send_raw_gcode`

Experimental raw G-code; disabled by default and length/control bounded.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `gcode` | `string` | yes |
| `approval_token` | `string` | yes |

## `send_raw_mqtt`

Send an experimental request-topic command.

Arbitrary topics and forbidden families remain blocked.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `family` | `string` | yes |
| `command` | `string` | yes |
| `parameters` | `object` | yes |
| `approval_token` | `string` | yes |

## `set_airduct`

Set a bounded X2D airduct channel with a one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `channel` | `integer` | yes |
| `percent` | `integer` | yes |
| `approval_token` | `string` | yes |

## `set_camera_recording`

Enable or disable on-printer camera recording.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `enabled` | `boolean` | yes |

## `set_chamber`

Request an X2D chamber target; catalogued but unverified writes fail closed.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `celsius` | `integer` | yes |
| `approval_token` | `string` | yes |

## `set_detection_options`

Experimental detection/print options; disabled by default.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `options` | `object` | yes |
| `approval_token` | `string` | yes |

## `set_fan`

Set a fan from 0-100 percent through bounded G-code.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `fan` | `integer` | yes |
| `percent` | `integer` | yes |

## `set_light`

Control either catalogued X2D light.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `node` | `string` | yes |
| `mode` | `string` | yes |

## `set_pressure_advance`

Experimental pressure-advance profile write; disabled by default.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `profile` | `object` | yes |
| `approval_token` | `string` | yes |

## `set_print_speed`

Set silent, standard, sport, or ludicrous speed.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `level` | `integer` | yes |

## `set_temperature`

Set a bounded temperature target with a one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `target` | `string` | yes |
| `celsius` | `integer` | yes |
| `approval_token` | `string` | yes |

## `set_timelapse`

Enable or disable on-printer timelapse capture.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `enabled` | `boolean` | yes |

## `skip_objects`

Skip validated positive object IDs with a one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `object_ids` | `array` | yes |
| `approval_token` | `string` | yes |

## `stop_printer`

Stop the active print with a one-use guarded approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `approval_token` | `string` | yes |

## `submit_stl_pipeline`

Convenience alias that prepares an STL workflow and stops before printer writes.

| Parameter | Type | Required |
| --- | --- | --- |
| `request` | `PreparePrintRequest` | yes |

## `transform_model`

Create a repaired/transformed immutable STL artifact.

| Parameter | Type | Required |
| --- | --- | --- |
| `artifact_id` | `string` | yes |
| `transform` | `TransformSpec` | yes |
| `repair` | `boolean` | no |

## `unload_filament`

Unload filament using a one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `job_id` | `string` | yes |
| `approval_token` | `string` | yes |

## `upload_printer_file`

Upload an immutable artifact over FTPS with a one-use approval.

| Parameter | Type | Required |
| --- | --- | --- |
| `printer_id` | `string` | yes |
| `artifact_id` | `string` | yes |
| `filename` | `string` | yes |
| `job_id` | `string` | yes |
| `approval_token` | `string` | yes |
