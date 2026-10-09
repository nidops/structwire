"""StructWire exception hierarchy."""


class StructWireError(Exception):
    """Base class for all StructWire errors."""


class SchemaError(StructWireError, ValueError):
    """Raised when a layout is invalid or ambiguous."""


class EncodeError(StructWireError, ValueError):
    """Raised when a value cannot be represented by a layout."""


class DecodeError(StructWireError, ValueError):
    """Raised when bytes do not satisfy a layout."""


class PrecisionError(DecodeError):
    """Valid numeric wire data cannot be represented without losing integer precision."""
