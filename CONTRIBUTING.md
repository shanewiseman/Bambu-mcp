# Contributing

Thank you for helping make LAN printer automation safer and more observable.
Before code changes, read `docs/architecture.md`, `docs/security.md`, and
`docs/provenance.md`. Do not consult or translate the legacy GPL fork while
implementing this clean-room core. New protocol claims need a source URL,
observation date, affected model/firmware, risk tier, and evidence label in the
capability matrix.

Use Python 3.12, install `.[dev]`, and run the full validation sequence from the
README. Add unit and contract tests for normal behavior and failure boundaries.
Tests requiring a physical printer must be marked/manual, must use a stable
fixture identity, and must follow `docs/hardware-validation.md`; never turn a
simulated result into a hardware-verified claim.

Pull requests should explain the user outcome, safety and compatibility impact,
protocol evidence, migrations, generated artifacts, and exact validation. Keep
secrets, captures, profiles with redistribution restrictions, and generated
printer identifiers out of Git.
