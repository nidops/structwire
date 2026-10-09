"""Encode and decode fixed-layout binary payloads."""

from .catalog import Catalog
from .codec import Codec
from .errors import DecodeError, EncodeError, SchemaError, StructWireError
from .formatting import format_mac_address, format_record, format_value
from .loaders import (
    catalog_from_mapping,
    catalog_from_yaml,
    layout_from_mapping,
    layout_from_yaml,
)
from .model import Field, Layout

__all__ = [
    "Catalog",
    "Codec",
    "DecodeError",
    "EncodeError",
    "Field",
    "Layout",
    "SchemaError",
    "StructWireError",
    "catalog_from_mapping",
    "catalog_from_yaml",
    "format_mac_address",
    "format_record",
    "format_value",
    "layout_from_mapping",
    "layout_from_yaml",
]

__version__ = "0.1.0.post1"
