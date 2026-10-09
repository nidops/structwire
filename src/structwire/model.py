"""Immutable public schema model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from .errors import SchemaError

if TYPE_CHECKING:
    from .codec import Codec

_INTEGER_KINDS: dict[str, tuple[int, bool, Literal["big", "little"]]] = {
    "u8": (1, False, "big"),
    "i8": (1, True, "big"),
    "u16be": (2, False, "big"),
    "u16le": (2, False, "little"),
    "i16be": (2, True, "big"),
    "i16le": (2, True, "little"),
    "u24be": (3, False, "big"),
    "u24le": (3, False, "little"),
    "i24be": (3, True, "big"),
    "i24le": (3, True, "little"),
    "u32be": (4, False, "big"),
    "u32le": (4, False, "little"),
    "i32be": (4, True, "big"),
    "i32le": (4, True, "little"),
    "u64be": (8, False, "big"),
    "u64le": (8, False, "little"),
    "i64be": (8, True, "big"),
    "i64le": (8, True, "little"),
}

_FLOAT_KINDS: dict[str, tuple[int, Literal["big", "little"]]] = {
    "f32be": (4, "big"),
    "f32le": (4, "little"),
    "f64be": (8, "big"),
    "f64le": (8, "little"),
}

_ALIASES = {
    "uint8": "u8",
    "int8": "i8",
    "uint16_be": "u16be",
    "uint16_le": "u16le",
    "int16_be": "i16be",
    "int16_le": "i16le",
    "uint24_be": "u24be",
    "uint24_le": "u24le",
    "int24_be": "i24be",
    "int24_le": "i24le",
    "uint32_be": "u32be",
    "uint32_le": "u32le",
    "int32_be": "i32be",
    "int32_le": "i32le",
    "uint64_be": "u64be",
    "uint64_le": "u64le",
    "int64_be": "i64be",
    "int64_le": "i64le",
    "float32_be": "f32be",
    "float32_le": "f32le",
    "float64_be": "f64be",
    "float64_le": "f64le",
    "raw": "bytes",
    "mac_address": "mac",
}

_SPECIAL_KINDS = {"bcd", "ascii", "bytes", "mac", "enum", "flags", "bool"}


def _schema_integer(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaError(f"{where} must be an integer")
    return value


def canonical_kind(kind: str) -> str:
    """Return a stable kind name, accepting kind aliases."""
    if not isinstance(kind, str):
        raise SchemaError("Field kind must be a string")
    key = kind.strip().lower().replace("-", "_")
    canonical = _ALIASES.get(key, key)
    if (
        canonical not in _INTEGER_KINDS
        and canonical not in _FLOAT_KINDS
        and canonical not in _SPECIAL_KINDS
    ):
        raise SchemaError(f"Unsupported field kind: {kind!r}")
    return canonical


def integer_spec(kind: str) -> tuple[int, bool, Literal["big", "little"]] | None:
    """Return ``(width, signed, byteorder)`` for an integer kind."""
    return _INTEGER_KINDS.get(canonical_kind(kind))


def float_spec(kind: str) -> tuple[int, Literal["big", "little"]] | None:
    """Return ``(width, byteorder)`` for a floating-point kind."""
    return _FLOAT_KINDS.get(canonical_kind(kind))


def _logical_bits(width: int, mask: int | None, shift: int) -> int:
    if mask is None:
        return width * 8
    return (mask >> shift).bit_length()


@dataclass(frozen=True, slots=True)
class Field:
    """One field in a binary layout.

    ``offset`` is a byte offset. When omitted, the field is placed after the
    furthest byte occupied so far. ``mask`` and ``shift`` address sub-fields
    within an integer-sized byte span.
    """

    name: str
    kind: str
    length: int | None = None
    offset: int | None = None
    mask: int | None = None
    shift: int = 0
    scale: float = 1.0
    bias: float = 0.0
    values: Mapping[int, str] = field(default_factory=dict)
    bits: Mapping[str, int] = field(default_factory=dict)
    byteorder: str = "big"
    description: str = ""
    unit: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise SchemaError("Field name must be non-empty")
        kind = canonical_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        for attribute in ("offset", "length", "mask"):
            value = getattr(self, attribute)
            if value is not None:
                _schema_integer(value, f"Field {self.name!r}: {attribute}")
        _schema_integer(self.shift, f"Field {self.name!r}: shift")
        if self.offset is not None and self.offset < 0:
            raise SchemaError(f"Field {self.name!r}: offset must be non-negative")
        if self.length is not None and self.length < 1:
            raise SchemaError(f"Field {self.name!r}: length must be >= 1")
        if self.shift < 0:
            raise SchemaError(f"Field {self.name!r}: shift must be non-negative")
        if self.shift and self.mask is None:
            raise SchemaError(f"Field {self.name!r}: shift requires a mask")
        for attribute in ("scale", "bias"):
            value = getattr(self, attribute)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SchemaError(f"Field {self.name!r}: {attribute} must be a finite number")
            try:
                finite = isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise SchemaError(f"Field {self.name!r}: scale and bias must be finite")
        if self.scale == 0:
            raise SchemaError(f"Field {self.name!r}: scale cannot be zero")
        if self.byteorder not in ("big", "little"):
            raise SchemaError(f"Field {self.name!r}: byteorder must be 'big' or 'little'")
        for attribute in ("description", "unit"):
            if not isinstance(getattr(self, attribute), str):
                raise SchemaError(f"Field {self.name!r}: {attribute} must be a string")
        if not isinstance(self.values, Mapping) or not isinstance(self.bits, Mapping):
            raise SchemaError(f"Field {self.name!r}: values/bits must be mappings")
        if self.values and kind != "enum":
            raise SchemaError(f"Field {self.name!r}: values is only valid for enum fields")
        if self.bits and kind != "flags":
            raise SchemaError(f"Field {self.name!r}: bits is only valid for flags fields")
        if any(not isinstance(label, str) for label in self.values.values()):
            raise SchemaError(f"Field {self.name!r}: enum labels must be strings")
        if any(not isinstance(name, str) or not name.strip() for name in self.bits):
            raise SchemaError(f"Field {self.name!r}: flag names must be non-empty strings")

        values = {
            _schema_integer(k, f"Field {self.name!r}: enum key"): v for k, v in self.values.items()
        }
        bits = {
            k: _schema_integer(v, f"Field {self.name!r}: flag mask") for k, v in self.bits.items()
        }
        if len(set(values.values())) != len(values):
            raise SchemaError(f"Field {self.name!r}: enum labels must be unique for encoding")
        object.__setattr__(self, "values", MappingProxyType(values))
        object.__setattr__(self, "bits", MappingProxyType(bits))

        if kind in {"ascii", "bytes"} and self.length is None:
            raise SchemaError(f"Field {self.name!r}: {kind} requires length")
        width = self.width
        if (kind in _INTEGER_KINDS or kind in _FLOAT_KINDS) and self.length not in (None, width):
            raise SchemaError(f"Field {self.name!r}: {kind} is exactly {width} byte(s)")
        if self.mask is not None:
            if self.mask <= 0 or self.mask.bit_length() > width * 8:
                raise SchemaError(
                    f"Field {self.name!r}: mask 0x{self.mask:X} does not fit {width} byte(s)"
                )
            shifted = self.mask >> self.shift
            if shifted == 0 or shifted & (shifted + 1):
                raise SchemaError(
                    f"Field {self.name!r}: mask must become contiguous low bits after shift"
                )
            if shifted << self.shift != self.mask:
                raise SchemaError(f"Field {self.name!r}: shift does not match mask")

        if kind == "mac" and self.length not in {None, 6}:
            raise SchemaError(f"Field {self.name!r}: mac fields are exactly 6 bytes")
        if self.mask is not None and (
            kind in _FLOAT_KINDS or kind in {"bcd", "ascii", "bytes", "mac"}
        ):
            raise SchemaError(f"Field {self.name!r}: mask is not valid for {kind}")
        if kind in {"enum", "flags", "bool"} and not 1 <= width <= 8:
            raise SchemaError(f"Field {self.name!r}: {kind} width must be between 1 and 8 bytes")
        if kind in {"enum", "flags"}:
            logical_bits = _logical_bits(width, self.mask, self.shift)
            logical_max = (1 << logical_bits) - 1
        if kind == "enum":
            if not values:
                raise SchemaError(f"Field {self.name!r}: enum requires values")
            invalid = [raw for raw in values if raw < 0 or raw > logical_max]
            if invalid:
                raise SchemaError(
                    f"Field {self.name!r}: enum value does not fit {logical_bits} bit(s)"
                )
        if kind == "flags":
            if not bits:
                raise SchemaError(f"Field {self.name!r}: flags requires bits")
            invalid = [mask for mask in bits.values() if mask <= 0 or mask > logical_max]
            if invalid:
                raise SchemaError(
                    f"Field {self.name!r}: flag mask 0x{invalid[0]:X} does not fit "
                    f"{logical_bits} bit(s)"
                )
        if kind in {"ascii", "bytes", "mac", "flags", "enum", "bool"} and (
            self.scale != 1.0 or self.bias != 0.0
        ):
            raise SchemaError(f"Field {self.name!r}: scale/bias is not valid for {kind}")

    @property
    def width(self) -> int:
        """Field width in bytes."""
        int_spec = _INTEGER_KINDS.get(self.kind)
        if int_spec is not None:
            return int_spec[0]
        flt_spec = _FLOAT_KINDS.get(self.kind)
        if flt_spec is not None:
            return flt_spec[0]
        if self.kind == "mac":
            return 6
        if self.kind == "bcd":
            return self.length or 1
        if self.kind in {"enum", "flags", "bool"}:
            return self.length or 1
        assert self.length is not None
        return self.length

    @property
    def effective_byteorder(self) -> Literal["big", "little"]:
        """Kind-defined numeric order, otherwise the supplied byteorder.

        BCD, ASCII and bytes retain wire order regardless of this parameter.
        """
        spec = _INTEGER_KINDS.get(self.kind)
        if spec is not None:
            return spec[2]
        flt = _FLOAT_KINDS.get(self.kind)
        if flt is not None:
            return flt[1]
        return cast(Literal["big", "little"], self.byteorder)

    @property
    def signed(self) -> bool:
        spec = _INTEGER_KINDS.get(self.kind)
        return bool(spec and spec[1])


@dataclass(frozen=True, slots=True)
class Layout:
    """Immutable declarative binary layout."""

    fields: tuple[Field, ...]
    name: str = ""
    description: str = ""
    size: int | None = None

    def __init__(
        self,
        *fields: Field,
        name: str = "",
        description: str = "",
        size: int | None = None,
    ) -> None:
        if size is not None:
            _schema_integer(size, "Layout size")
        if not isinstance(name, str):
            raise SchemaError("Layout name must be a string")
        if not isinstance(description, str):
            raise SchemaError("Layout description must be a string")
        if any(not isinstance(item, Field) for item in fields):
            raise SchemaError("Layout fields must be Field objects")
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "size", size)
        if size is not None and size < 0:
            raise SchemaError("Layout size must be non-negative")
        if len({item.name for item in fields}) != len(fields):
            raise SchemaError("Field names must be unique")

    def compile(self) -> Codec:
        """Compile this layout into a reusable codec."""
        from .codec import Codec

        return Codec(self)

    def encode(self, values: Mapping[str, Any], *, require_all: bool = True) -> bytes:
        """Compile and encode in one call."""
        return self.compile().encode(values, require_all=require_all)

    def decode(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Compile and decode in one call."""
        return self.compile().decode(payload, strict=strict)
