"""Compiled encoder/decoder implementation."""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import DecodeError, EncodeError, SchemaError
from .model import Field, Layout, float_spec, integer_spec


@dataclass(frozen=True, slots=True)
class _CompiledField:
    field: Field
    offset: int

    @property
    def end(self) -> int:
        return self.offset + self.field.width


class Codec:
    """Compiled, reusable binary codec.

    Layout validation and offsets are resolved once in the constructor. A
    ``Codec`` holds no per-call mutable state and can therefore be reused by
    independent callers.
    """

    __slots__ = ("_fields", "_layout", "_size")

    def __init__(self, layout: Layout) -> None:
        self._layout = layout
        cursor = 0
        compiled: list[_CompiledField] = []
        for field in layout.fields:
            offset = cursor if field.offset is None else field.offset
            item = _CompiledField(field, offset)
            compiled.append(item)
            cursor = max(cursor, item.end)
        if layout.size is not None and layout.size < cursor:
            raise SchemaError(
                f"Layout {layout.name!r} declares size {layout.size}, "
                f"but fields require at least {cursor} byte(s)"
            )
        _check_overlaps(compiled)
        self._fields = tuple(compiled)
        self._size = max(cursor, layout.size or 0)

    @property
    def layout(self) -> Layout:
        return self._layout

    @property
    def size(self) -> int:
        """Exact encoded payload size in bytes."""
        return self._size

    @property
    def fields(self) -> tuple[Field, ...]:
        return tuple(item.field for item in self._fields)

    def describe(self) -> dict[str, Any]:
        """Return a serialization-friendly description of the compiled layout."""
        return {
            "name": self._layout.name,
            "description": self._layout.description,
            "size": self._size,
            "fields": [
                {
                    "name": item.field.name,
                    "kind": item.field.kind,
                    "offset": item.offset,
                    "length": item.field.width,
                    "mask": item.field.mask,
                    "shift": item.field.shift,
                    "scale": item.field.scale,
                    "bias": item.field.bias,
                    "byteorder": item.field.effective_byteorder,
                    "values": dict(item.field.values),
                    "bits": dict(item.field.bits),
                    "unit": item.field.unit,
                    "description": item.field.description,
                }
                for item in self._fields
            ],
        }

    def decode(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Decode a bytes-like payload into a new mapping of named field values.

        ``strict=True`` requires exactly ``size`` bytes. With ``strict=False``,
        trailing bytes are ignored; short payloads still raise ``DecodeError``.
        Malformed field data and scaled values that lose raw integer precision
        also raise ``DecodeError``. Mutable input is copied; inputs are never modified.
        """
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise DecodeError("Payload must be bytes, bytearray or memoryview")
        try:
            raw = bytes(payload)
        except ValueError as exc:
            raise DecodeError("Payload memoryview is no longer accessible") from exc
        if len(raw) < self._size:
            raise DecodeError(f"Payload has {len(raw)} byte(s); layout requires {self._size}")
        if strict and len(raw) != self._size:
            raise DecodeError(f"Payload has {len(raw)} byte(s); expected exactly {self._size}")
        result: dict[str, Any] = {}
        for item in self._fields:
            fragment = raw[item.offset : item.end]
            result[item.field.name] = _decode_field(item.field, fragment)
        return result

    def encode(self, values: Mapping[str, Any], *, require_all: bool = True) -> bytes:
        """Encode named values as canonical bytes without modifying the mapping.

        ``require_all=True`` requires every field. With ``require_all=False``,
        omitted fields leave their storage bits zero. Unused bytes and bits are
        always zero, so unrepresented input bits cannot survive a round trip.
        Non-mapping inputs, unknown names, missing required fields, invalid values,
        out-of-range numbers and off-grid scaled integers raise ``EncodeError``.
        """
        if not isinstance(values, Mapping):
            raise EncodeError("Values must be a mapping of field names to values")
        unknown = set(values) - {item.field.name for item in self._fields}
        if unknown:
            raise EncodeError(f"Unknown field(s): {', '.join(sorted(map(str, unknown)))}")
        if require_all:
            missing = [item.field.name for item in self._fields if item.field.name not in values]
            if missing:
                raise EncodeError(f"Missing field(s): {', '.join(missing)}")

        output = bytearray(self._size)
        for item in self._fields:
            if item.field.name not in values:
                continue
            encoded, write_mask = _encode_field(item.field, values[item.field.name])
            for index, byte in enumerate(encoded):
                absolute = item.offset + index
                mask = write_mask[index]
                output[absolute] = (output[absolute] & ~mask) | (byte & mask)
        return bytes(output)


def _check_overlaps(fields: list[_CompiledField]) -> None:
    # Full-width writers need one interval, regardless of their width or offset.
    # Masked kinds have at most eight bytes, so each needs at most eight claims.
    claims: list[tuple[int, int, int, str]] = []
    for item in fields:
        if item.field.mask is None:
            claims.append((item.offset, item.end, 0xFF, item.field.name))
        else:
            for index, mask in enumerate(_write_masks(item.field)):
                if mask:
                    start = item.offset + index
                    claims.append((start, start + 1, mask, item.field.name))

    claimed_end = 0
    claimed_mask = 0
    for start, end, mask, name in sorted(claims, key=lambda claim: claim[0]):
        if start >= claimed_end:
            claimed_mask = 0
        overlap = claimed_mask & mask
        if overlap:
            raise SchemaError(
                f"Fields overlap ambiguously at byte {start}: field {name!r} "
                f"reuses bit mask 0x{overlap:02X}"
            )
        # Only full-byte claims span multiple bytes. Any accepted overlap must
        # therefore consist of disjoint masks at the same single byte.
        claimed_mask |= mask
        claimed_end = end


def _write_masks(field: Field) -> bytes:
    if field.mask is None:
        return b"\xff" * field.width
    return field.mask.to_bytes(field.width, field.effective_byteorder, signed=False)


def _decode_field(field: Field, fragment: bytes) -> Any:
    kind = field.kind
    int_spec = integer_spec(kind)
    if int_spec is not None:
        _, signed, byteorder = int_spec
        if field.mask is None:
            value = int.from_bytes(fragment, byteorder, signed=signed)
        else:
            container = int.from_bytes(fragment, byteorder, signed=False)
            masked = (container & field.mask) >> field.shift
            value = _sign_extend(masked, _mask_width(field.mask, field.shift)) if signed else masked
        return _physical(field, value)

    flt = float_spec(kind)
    if flt is not None:
        if field.mask is not None:
            raise SchemaError(f"Field {field.name!r}: masks are not supported for floats")
        prefix = ">" if flt[1] == "big" else "<"
        fmt = "f" if flt[0] == 4 else "d"
        value = struct.unpack(prefix + fmt, fragment)[0]
        return _physical(field, value)

    if kind == "bcd":
        digits: list[str] = []
        for byte in fragment:
            high, low = byte >> 4, byte & 0x0F
            if high > 9 or low > 9:
                raise DecodeError(f"Field {field.name!r}: invalid BCD byte 0x{byte:02X}")
            digits.extend((str(high), str(low)))
        try:
            value = int("".join(digits))
        except ValueError as exc:
            raise DecodeError(
                f"Field {field.name!r}: BCD exceeds integer conversion limit"
            ) from exc
        return _physical(field, value)

    if kind == "ascii":
        try:
            return fragment.decode("ascii").rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise DecodeError(f"Field {field.name!r}: invalid ASCII") from exc

    if kind == "bytes":
        return fragment

    if kind == "mac":
        raw_mac = fragment[::-1] if field.byteorder == "little" else fragment
        return ":".join(f"{byte:02X}" for byte in raw_mac)

    raw = int.from_bytes(fragment, field.effective_byteorder, signed=False)
    if field.mask is not None:
        raw = (raw & field.mask) >> field.shift

    if kind == "enum":
        return field.values.get(raw, raw)
    if kind == "flags":
        return {name: bool(raw & mask) for name, mask in field.bits.items()}
    if kind == "bool":
        return bool(raw)
    raise AssertionError(kind)


def _encode_field(field: Field, value: Any) -> tuple[bytes, bytes]:
    kind = field.kind
    masks = _write_masks(field)
    raw_value: int
    int_spec = integer_spec(kind)
    if int_spec is not None:
        width, signed, byteorder = int_spec
        numeric = _raw_numeric(field, value, integral=True)
        assert isinstance(numeric, int)
        if field.mask is None:
            try:
                return numeric.to_bytes(width, byteorder, signed=signed), masks
            except OverflowError as exc:
                raise EncodeError(f"Field {field.name!r}: value does not fit {kind}") from exc
        bits = _mask_width(field.mask, field.shift)
        encoded_numeric = _fit_masked_integer(field, numeric, bits, signed)
        container = (encoded_numeric << field.shift) & field.mask
        return container.to_bytes(width, byteorder, signed=False), masks

    flt = float_spec(kind)
    if flt is not None:
        if field.mask is not None:
            raise SchemaError(f"Field {field.name!r}: masks are not supported for floats")
        numeric = float(_raw_numeric(field, value, integral=False))
        prefix = ">" if flt[1] == "big" else "<"
        fmt = "f" if flt[0] == 4 else "d"
        try:
            return struct.pack(prefix + fmt, numeric), masks
        except (OverflowError, struct.error) as exc:
            raise EncodeError(f"Field {field.name!r}: {value!r} does not fit {kind}") from exc

    if kind == "bcd":
        numeric = _raw_numeric(field, value, integral=True)
        assert isinstance(numeric, int)
        try:
            digits = str(numeric)
        except ValueError as exc:
            raise EncodeError(
                f"Field {field.name!r}: BCD exceeds integer conversion limit"
            ) from exc
        max_digits = field.width * 2
        if numeric < 0 or len(digits) > max_digits:
            raise EncodeError(
                f"Field {field.name!r}: {numeric} does not fit {field.width}-byte BCD"
            )
        digits = digits.zfill(max_digits)
        encoded = bytes((int(digits[i]) << 4) | int(digits[i + 1]) for i in range(0, max_digits, 2))
        return encoded, masks

    if kind == "ascii":
        if not isinstance(value, str):
            raise EncodeError(f"Field {field.name!r}: ASCII value must be str")
        try:
            raw = value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise EncodeError(f"Field {field.name!r}: value is not ASCII") from exc
        if len(raw) > field.width:
            raise EncodeError(f"Field {field.name!r}: string is longer than {field.width} byte(s)")
        return raw.ljust(field.width, b"\x00"), masks

    if kind == "bytes":
        if isinstance(value, int):
            raise EncodeError(f"Field {field.name!r}: bytes value required, not integer length")
        try:
            raw = bytes(value)
        except (TypeError, ValueError) as exc:
            raise EncodeError(f"Field {field.name!r}: bytes value required") from exc
        if len(raw) != field.width:
            raise EncodeError(
                f"Field {field.name!r}: expected {field.width} byte(s), got {len(raw)}"
            )
        return raw, masks

    if kind == "mac":
        return _encode_mac(field, value), masks

    if kind == "enum":
        raw_value = _enum_raw(field, value)
    elif kind == "flags":
        raw_value = _flags_raw(field, value)
    elif kind == "bool":
        raw_value = _bool_raw(field, value)
    else:
        raise AssertionError(kind)

    if field.mask is not None:
        width = _mask_width(field.mask, field.shift)
        if raw_value < 0 or raw_value >= 1 << width:
            raise EncodeError(f"Field {field.name!r}: value does not fit mask 0x{field.mask:X}")
        raw_value = (raw_value << field.shift) & field.mask
    try:
        return raw_value.to_bytes(field.width, field.effective_byteorder, signed=False), masks
    except OverflowError as exc:
        raise EncodeError(
            f"Field {field.name!r}: value does not fit {field.width} byte(s)"
        ) from exc


def _raw_numeric(field: Field, value: Any, *, integral: bool) -> int | float:
    numeric: int | float
    if isinstance(value, bool):
        numeric = int(value)
    elif isinstance(value, (int, float)):
        numeric = value
    else:
        raise EncodeError(f"Field {field.name!r}: numeric value required")
    if integral and field.scale == 1.0 and field.bias == 0.0 and isinstance(numeric, int):
        return int(numeric)
    try:
        floating = float(numeric)
        raw = (floating - field.bias) / field.scale
    except OverflowError as exc:
        raise EncodeError(f"Field {field.name!r}: numeric value is too large") from exc
    if integral:
        if isinstance(numeric, int) and floating != numeric:
            raise EncodeError(
                f"Field {field.name!r}: scaling cannot preserve integer input precision"
            )
        if not math.isfinite(raw):
            raise EncodeError(f"Field {field.name!r}: finite numeric value required")
        rounded = round(raw)
        tolerance = 1e-12
        if field.scale != 1.0 or field.bias != 0.0:
            # Inverting a decoded physical value can introduce one floating-point
            # step of arithmetic error, even when the raw integer is exact.
            tolerance = max(tolerance, math.ulp(raw))
        on_grid = math.isclose(raw, rounded, rel_tol=0.0, abs_tol=tolerance)
        if not on_grid and (field.scale != 1.0 or field.bias != 0.0):
            # Subtracting a large bias can amplify cancellation noise. Accept
            # a candidate only if its forward conversion reproduces the input.
            on_grid = rounded * field.scale + field.bias == numeric
        # Reject half-count values even when the tolerance reaches half a count.
        if abs(raw - rounded) >= 0.5 or not on_grid:
            raise EncodeError(
                f"Field {field.name!r}: {value!r} is not exactly representable with "
                f"scale={field.scale} bias={field.bias}"
            )
        if field.scale != 1.0 or field.bias != 0.0:
            forward = rounded * field.scale + field.bias
            if not math.isfinite(forward) or abs(forward - floating) / abs(field.scale) >= 0.5:
                raise EncodeError(
                    f"Field {field.name!r}: scaling cannot preserve integer input precision"
                )
        return int(rounded)
    if math.isfinite(floating) and not math.isfinite(raw):
        raise EncodeError(f"Field {field.name!r}: inverse scaling overflows floating-point range")
    return raw


def _physical(field: Field, raw: int | float) -> int | float:
    if field.scale == 1.0 and field.bias == 0.0:
        return raw
    try:
        physical = raw * field.scale + field.bias
    except OverflowError as exc:
        raise DecodeError(
            f"Field {field.name!r}: scaled value overflows floating-point range"
        ) from exc
    if isinstance(raw, int):
        try:
            recovered = _raw_numeric(field, physical, integral=True)
        except EncodeError as exc:
            raise DecodeError(
                f"Field {field.name!r}: scaling cannot preserve integer precision; "
                "use an unscaled field to obtain the raw integer"
            ) from exc
        if recovered != raw:
            raise DecodeError(
                f"Field {field.name!r}: scaling cannot preserve integer precision; "
                "use an unscaled field to obtain the raw integer"
            )
    elif math.isfinite(raw) and not math.isfinite(physical):
        raise DecodeError(f"Field {field.name!r}: scaled value overflows floating-point range")
    return physical


def _mask_width(mask: int | None, shift: int) -> int:
    assert mask is not None
    return (mask >> shift).bit_length()


def _sign_extend(value: int, width: int) -> int:
    sign = 1 << (width - 1)
    return value - (1 << width) if value & sign else value


def _fit_masked_integer(field: Field, value: int, width: int, signed: bool) -> int:
    if signed:
        minimum = -(1 << (width - 1))
        maximum = (1 << (width - 1)) - 1
        if not minimum <= value <= maximum:
            raise EncodeError(f"Field {field.name!r}: value does not fit signed {width}-bit mask")
        return value & ((1 << width) - 1)
    if not 0 <= value < 1 << width:
        raise EncodeError(f"Field {field.name!r}: value does not fit unsigned {width}-bit mask")
    return value


def _bool_raw(field: Field, value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in {0, 1}:
        return value
    raise EncodeError(f"Field {field.name!r}: bool value must be True/False or 0/1")


def _enum_raw(field: Field, value: Any) -> int:
    if isinstance(value, str):
        for raw, label in field.values.items():
            if label == value:
                return raw
        raise EncodeError(f"Field {field.name!r}: unknown enum label {value!r}")
    if isinstance(value, int):
        return value
    raise EncodeError(f"Field {field.name!r}: enum value must be label or integer")


def _flags_raw(field: Field, value: Any) -> int:
    if isinstance(value, Mapping):
        unknown = set(value) - set(field.bits)
        if unknown:
            raise EncodeError(
                f"Field {field.name!r}: unknown flag(s): {', '.join(sorted(map(str, unknown)))}"
            )
        raw = 0
        for name, mask in field.bits.items():
            state = value.get(name, False)
            if not isinstance(state, bool) and not (isinstance(state, int) and state in {0, 1}):
                raise EncodeError(f"Field {field.name!r}: flag {name!r} must be True/False or 0/1")
            if bool(state):
                raw |= mask
        return raw
    if isinstance(value, int):
        return value
    raise EncodeError(f"Field {field.name!r}: flags value must be mapping or integer")


def _encode_mac(field: Field, value: Any) -> bytes:
    if isinstance(value, str):
        if (
            re.fullmatch(r"[0-9a-fA-F]{2}([:-])(?:[0-9a-fA-F]{2}\1){4}[0-9a-fA-F]{2}", value)
            is None
        ):
            raise EncodeError(f"Field {field.name!r}: invalid MAC address {value!r}")
        raw = bytes.fromhex(value.replace(":", "").replace("-", ""))
    else:
        if isinstance(value, int):
            raise EncodeError(f"Field {field.name!r}: MAC must be text or six bytes")
        try:
            raw = bytes(value)
        except (TypeError, ValueError) as exc:
            raise EncodeError(f"Field {field.name!r}: MAC must be text or six bytes") from exc
    if len(raw) != 6:
        raise EncodeError(f"Field {field.name!r}: MAC address must contain six bytes")
    return raw[::-1] if field.byteorder == "little" else raw
