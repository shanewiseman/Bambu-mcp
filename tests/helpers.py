"""Shared test helpers that are safe to import from focused test runs."""

from bambu_mcp.container import Container


def ingest(container: Container, filename: str, content: bytes) -> str:
    """Store an artifact and return its content-addressed identifier."""
    with container.database.session() as session:
        artifact = container.artifacts.ingest_bytes(session, filename, content)
        return artifact.id
