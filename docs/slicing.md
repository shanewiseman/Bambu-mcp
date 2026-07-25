# Slicing and 3MF guide

The slicer boundary exists because Bambu Studio is a large AGPL-3.0 application
with different operational and licensing risks from the Python core. Version
2.7.1.62 is pinned to release tag `v02.07.01.62` and commit `42d319c6692fa8e64790fddf0cdaafd2a4254bcc`; the build fails if the tag resolves elsewhere.
The sidecar is non-root, read-only, and attached only to an internal network.

## Inputs

The core accepts immutable STL/3MF IDs plus explicit printer, bed, process,
plate, nozzle diameter(s), filament profiles, supports, orientation, copy count,
and material routes. The sidecar maps profile names to full JSON files below
`/profiles`; path syntax and missing files are rejected.

The official CLI uses `--load-settings`, `--load-filaments`, `--slice`, and
`--export-3mf`. This project executes an argument array directly—never a shell.
The sidecar always maps `supports` to the pinned CLI's `--enable-support`
print override (`0` or `1`), so a process profile cannot silently replace the
request. For `copies > 1`, STL input maps to `--clone-objects`; Bambu project
3MF input maps to the selected-plate `--repetitions` transform. The pinned CLI
rejects repetitions for a generic, non-Bambu 3MF instead of ignoring the copy
request, and that failure is returned to the caller. These mappings follow the
upstream definitions for
[`enable_support`](https://github.com/bambulab/BambuStudio/blob/42d319c6692fa8e64790fddf0cdaafd2a4254bcc/src/libslic3r/PrintConfig.cpp#L5075-L5080),
[`repetitions`](https://github.com/bambulab/BambuStudio/blob/42d319c6692fa8e64790fddf0cdaafd2a4254bcc/src/libslic3r/PrintConfig.cpp#L9572-L9577), and
[`clone_objects`](https://github.com/bambulab/BambuStudio/blob/42d319c6692fa8e64790fddf0cdaafd2a4254bcc/src/libslic3r/PrintConfig.cpp#L9690-L9695).
Outputs land at a job-specific path in the shared artifact volume and are
re-ingested by hash after validation.

## Startup and dual-nozzle gates

`/readyz` executes the pinned binary's help command. The container reports the
compiled source version. Dual-nozzle slicing additionally requires
`BAMBU_DUAL_NOZZLE_SMOKE_OK=true`, which should be set only after a golden X2D
single/dual profile suite succeeds for the exact image and profile bundle.

If readiness or the dual test fails, the core retains ingestion, inspection,
transformation, and a pre-sliced `.gcode.3mf` path. It rejects automatic slicing
rather than silently falling back to a different printer/nozzle profile.

## Output validation

A `.gcode.3mf` must be a safe ZIP, contain `[Content_Types].xml` and at least one
`Metadata/*.gcode`, stay within entry/expanded-size/compression limits, contain
no traversal/symlink paths, and have parseable model XML when present. The plan
binds the exact output SHA-256 and reported metadata. Target model/profile,
plate, object IDs, material/nozzle mapping, and live preflight are validated
again before printer upload.

## Licensing and provenance

The repository does not distribute Studio binaries or official profiles. The
sidecar Dockerfile obtains the upstream AGPL source tag and builds it in a
separate stage. Anyone distributing the resulting image must provide compliant
corresponding source and notices. Public release remains gated on legal review;
see [provenance](provenance.md) and the [release checklist](release-checklist.md).
