"""Named collections of compiled codecs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any

from .codec import Codec
from .errors import SchemaError
from .model import Layout


class Catalog(Mapping[str, Codec]):
    """Immutable mapping of codec names to compiled :class:`Codec` objects."""

    __slots__ = ("_codecs",)

    def __init__(self, layouts: Mapping[str, Layout | Codec]) -> None:
        if not isinstance(layouts, Mapping):
            raise SchemaError(
                "Catalog layouts must be a mapping of names to Layout or Codec objects"
            )
        if not layouts:
            raise SchemaError("Catalog must contain at least one codec")
        compiled: dict[str, Codec] = {}
        for raw_name, layout_or_codec in layouts.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise SchemaError("Catalog codec names must be non-empty strings")
            name = raw_name.strip()
            if name in compiled:
                raise SchemaError(f"Duplicate codec name: {name!r}")
            if not isinstance(layout_or_codec, (Layout, Codec)):
                raise SchemaError(f"Catalog {name!r}: expected a Layout or Codec object")
            codec = (
                layout_or_codec if isinstance(layout_or_codec, Codec) else layout_or_codec.compile()
            )
            if codec.layout.name and codec.layout.name != name:
                raise SchemaError(
                    f"Catalog key {name!r} conflicts with layout name {codec.layout.name!r}"
                )
            compiled[name] = codec
        self._codecs: Mapping[str, Codec] = MappingProxyType(compiled)

    def __getitem__(self, name: str) -> Codec:
        try:
            return self._codecs[name]
        except KeyError as exc:
            raise KeyError(f"Unknown codec {name!r}") from exc

    def __iter__(self) -> Iterator[str]:
        return iter(self._codecs)

    def __len__(self) -> int:
        return len(self._codecs)

    @property
    def names(self) -> tuple[str, ...]:
        """Codec names in declaration order."""
        return tuple(self._codecs)

    def encode(
        self,
        name: str,
        values: Mapping[str, Any],
        *,
        require_all: bool = True,
    ) -> bytes:
        """Encode values with a named codec."""
        return self[name].encode(values, require_all=require_all)

    def decode(
        self,
        name: str,
        payload: bytes | bytearray | memoryview,
        *,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Decode bytes with a named codec."""
        return self[name].decode(payload, strict=strict)

    def describe(self) -> dict[str, dict[str, Any]]:
        """Return a serializable description of each named codec."""
        return {name: codec.describe() for name, codec in self._codecs.items()}
