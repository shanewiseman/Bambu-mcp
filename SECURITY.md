# Security policy

Bambu MCP is pre-1.0 and has not received a third-party security audit. Do not
expose it directly to the public Internet or an untrusted printer network.

Report suspected vulnerabilities privately through GitHub's **Security → Report
a vulnerability** flow. Do not open a public issue containing credentials,
printer serials, network captures, or exploit details. Maintainers will
acknowledge a report within five business days and coordinate remediation and
disclosure.

Supported security fixes target the latest release and the default branch.
Firmware, access-code retrieval/manipulation, cloud credentials, arbitrary MQTT
topics, and unconstrained host paths are outside the product boundary by design.
See [docs/security.md](docs/security.md) for deployment controls and limitations.
