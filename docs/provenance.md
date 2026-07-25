# Clean-room provenance ledger

This repository is an independent Python implementation. Contributors must not
copy, translate, or consult the legacy GPL fork while writing core code. The
frozen behavioral baseline in `IMPLEMENTATION_PLAN.md` is the only legacy input.

| Input | Use | Accessed | License/authority | Incorporated material |
| --- | --- | --- | --- | --- |
| Bambu Lab X2D product article | Official hardware capabilities | 2026-07-25 | Bambu Lab publication | Facts/links only; no copied media |
| Bambu Studio release `v02.07.01.62` / commit `42d319c6692fa8e64790fddf0cdaafd2a4254bcc` | Version pin and known X2D/FTS fixes | 2026-07-25 | Upstream AGPL-3.0 | Source obtained only in isolated sidecar build |
| Bambu Studio CLI and Docker wiki | Argument/build behavior | 2026-07-25 | Upstream documentation | Interface facts and links |
| MCP Python SDK v1 docs | FastMCP stdio/Streamable HTTP interface | 2026-07-25 | MIT upstream | Public API usage |
| OpenBambuAPI MQTT/FTP/TLS docs | Community-observed LAN behavior | 2026-07-25 | Repository terms apply | Facts re-expressed; CA bundle copied with source attribution |
| OpenBambuAPI `examples/ca_cert.pem` | TLS trust anchors | 2026-07-25 | Vendor certificates/community distribution | Exact PEM, SHA-256 `168852cde67cd9c7648de5f95b46f7b950d1627966d2da6a968fd9ef9d034910` |
| Bambuddy public README/releases | High-level X2D/FTS/slicer observations | 2026-07-25 | AGPL-3.0 project | Behavioral observations only; no source consulted/copied |
| Bambu security white paper | LAN/Developer Mode threat context | 2026-07-25 | Bambu Lab publication | Facts/links only |

Primary links are in the protocol matrix and implementation plan. Generated test
archives and models are authored in the test suite. Official profiles, Studio
binaries, printer captures, and legacy implementation code are not committed.

## Release gate

Before applying Apache-2.0 or distributing images, a qualified reviewer must
confirm authorship/provenance, dependencies and notices, Bambu Studio AGPL
corresponding-source process, CA certificate redistribution, trademarks, profile
rights, generated artifacts, and clean-room controls. Record reviewer/date/scope
in this ledger and replace `LICENSE.md` only after approval.
