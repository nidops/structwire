"""Generated comparisons with Python's standard binary encoders."""

from __future__ import annotations

import struct

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from structwire import EncodeError, Field, Layout

INTEGER_CASES = [
    (f"{sign}{width}{order}", width, sign == "i", "little" if order == "le" else "big")
    for sign in ("u", "i")
    for width in (8, 16, 24, 32, 64)
    for order in (("",) if width == 8 else ("be", "le"))
]
STRUCT_FORMATS = {
    (8, False): "B",
    (8, True): "b",
    (16, False): "H",
    (16, True): "h",
    (32, False): "I",
    (32, True): "i",
    (64, False): "Q",
    (64, True): "q",
}


@pytest.mark.parametrize("kind,width,signed,byteorder", INTEGER_CASES)
@settings(max_examples=100, derandomize=True, deadline=None)
@given(data=st.data())
def test_integer_matches_standard_library(kind, width, signed, byteorder, data) -> None:
    minimum = -(1 << (width - 1)) if signed else 0
    maximum = (1 << (width - int(signed))) - 1
    value = data.draw(st.integers(minimum, maximum))
    codec = Layout(Field("value", kind)).compile()
    expected = value.to_bytes(width // 8, byteorder, signed=signed)
    if width != 24:
        prefix = "<" if byteorder == "little" else ">"
        assert expected == struct.pack(prefix + STRUCT_FORMATS[width, signed], value)
    assert codec.encode({"value": value}) == expected
    assert codec.decode(expected) == {"value": value}


@pytest.mark.parametrize("width", [32, 64])
@pytest.mark.parametrize("byteorder", ["le", "be"])
@settings(max_examples=100, derandomize=True, deadline=None)
@given(data=st.data())
def test_float_matches_standard_library(width, byteorder, data) -> None:
    value = data.draw(st.floats(width=width, allow_nan=False, allow_infinity=False))
    codec = Layout(Field("value", f"f{width}{byteorder}")).compile()
    prefix = "<" if byteorder == "le" else ">"
    expected = struct.pack(prefix + ("f" if width == 32 else "d"), value)
    assert codec.encode({"value": value}) == expected
    assert codec.encode(codec.decode(expected)) == expected


@settings(max_examples=250, derandomize=True, deadline=None)
@given(high=st.integers(0, 15), low=st.integers(0, 15))
def test_disjoint_masks_preserve_each_others_bits(high: int, low: int) -> None:
    codec = Layout(
        Field("high", "u8", mask=0xF0, shift=4),
        Field("low", "u8", offset=0, mask=0x0F),
    ).compile()
    expected = bytes([(high << 4) | low])
    assert codec.encode({"high": high, "low": low}) == expected
    assert codec.decode(expected) == {"high": high, "low": low}


@settings(max_examples=500, derandomize=True, deadline=None)
@given(
    raw=st.integers(0, 2**32 - 1),
    scale=st.sampled_from([0.01, 0.1, 0.3, 1.25, -0.1]),
    bias=st.sampled_from([-1000.0, -1.0, 0.0, 0.1, 1000.0]),
)
def test_scaled_u32_recovers_original_integer(raw: int, scale: float, bias: float) -> None:
    codec = Layout(Field("value", "u32be", scale=scale, bias=bias)).compile()
    payload = struct.pack(">I", raw)
    assert codec.encode(codec.decode(payload)) == payload


@pytest.mark.parametrize("byteorder", ["le", "be"])
@settings(max_examples=100, derandomize=True, deadline=None)
@given(signed=st.integers(-128, 127), unsigned=st.integers(0, 255))
def test_shared_multibyte_masks_match_wire_order(byteorder, signed, unsigned) -> None:
    codec = Layout(
        Field("signed", f"i16{byteorder}", mask=0xFF00, shift=8),
        Field("unsigned", f"u16{byteorder}", offset=0, mask=0x00FF),
    ).compile()
    prefix = "<" if byteorder == "le" else ">"
    expected = struct.pack(prefix + "H", ((signed & 0xFF) << 8) | unsigned)
    assert codec.encode({"signed": signed, "unsigned": unsigned}) == expected
    assert codec.decode(expected) == {"signed": signed, "unsigned": unsigned}


@pytest.mark.parametrize("kind,width,signed,byteorder", INTEGER_CASES)
def test_all_integer_boundaries(kind, width, signed, byteorder) -> None:
    minimum = -(1 << (width - 1)) if signed else 0
    maximum = (1 << (width - int(signed))) - 1
    codec = Layout(Field("value", kind)).compile()
    for value in (minimum, minimum + 1, 0, maximum - 1, maximum):
        expected = value.to_bytes(width // 8, byteorder, signed=signed)
        assert codec.encode({"value": value}) == expected
        assert codec.decode(expected) == {"value": value}
    for value in (minimum - 1, maximum + 1):
        with pytest.raises(EncodeError, match="does not fit"):
            codec.encode({"value": value})


@pytest.mark.parametrize("kind,width,signed,byteorder", INTEGER_CASES)
def test_masked_integer_boundaries(kind, width, signed, byteorder) -> None:
    logical_bits, shift = width - 2, 1
    mask = ((1 << logical_bits) - 1) << shift
    minimum = -(1 << (logical_bits - 1)) if signed else 0
    maximum = (1 << (logical_bits - int(signed))) - 1
    codec = Layout(Field("value", kind, mask=mask, shift=shift)).compile()
    for value in (minimum, 0, maximum):
        raw = (value & ((1 << logical_bits) - 1)) << shift
        expected = raw.to_bytes(width // 8, byteorder)
        assert codec.encode({"value": value}) == expected
        assert codec.decode(expected) == {"value": value}
    for value in (minimum - 1, maximum + 1):
        with pytest.raises(EncodeError, match="does not fit"):
            codec.encode({"value": value})
