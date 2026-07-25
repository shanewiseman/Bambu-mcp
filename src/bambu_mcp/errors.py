"""Domain exceptions exposed consistently by MCP and HTTP adapters."""


class BambuMCPError(Exception):
    """Base class for expected service errors."""


class NotFoundError(BambuMCPError):
    """A requested record or artifact does not exist."""


class ConflictError(BambuMCPError):
    """The operation conflicts with current durable state."""


class SafetyError(BambuMCPError):
    """A safety boundary rejected an operation."""


class ValidationError(BambuMCPError):
    """Input or an external artifact failed domain validation."""


class ProtocolError(BambuMCPError):
    """A printer protocol operation failed or was not acknowledged."""


class SlicerError(BambuMCPError):
    """The isolated slicer rejected or failed a job."""
