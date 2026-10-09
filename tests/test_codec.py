from __future__ import annotations

import math
import struct
import sys
from collections import UserDict
from types import MappingProxyType

import pytest

from structwire import Catalog, DecodeError, EncodeError, Field, Layout, SchemaError


@pytest.mark.parametrize("kind", ["enum", "flags"])
@pytest.mark.parametrize("value", [1.5, float("nan")])
def test_enum_and_flags_reject_non_integer_raw_values(kind: str, value: float) -> None:
    field = (
        Field("state", kind, values={1: "active"})
        if kind == "enum"
        else Field("state", kind, bits={"active": 1})
    )
    with pytest.raises(EncodeError, match="integer"):
        Layout(field).encode({"state": value})


def test_large_fractional_integer_is_not_silently_rounded() -> None:
    codec = Layout(Field("counter", "u64be")).compile()
    with pytest.raises(EncodeError, match="not exactly representable"):
        codec.encode({"counter": 1_000_000_000_000.25})


@pytest.mark.parametrize("scale,raw", [(0.01, 958682846), (0.1, 1812140441), (0.3, 127978094)])
def test_large_scaled_integer_roundtrip_tolerates_arithmetic_noise(scale: float, raw: int) -> None:
    codec = Layout(Field("value", "u32be", scale=scale)).compile()
    payload = raw.to_bytes(4, "big")
    assert codec.encode(codec.decode(payload)) == payload


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_integer_values_raise_encode_error(value: float) -> None:
    with pytest.raises(EncodeError, match="finite"):
        Layout(Field("count", "u8")).encode({"count": value})


def test_sequential_bcd_and_integers_round_trip() -> None:
    codec = Layout(
        Field("batch", "bcd", length=2),
        Field("quantity", "uint8"),
        Field("group", "bcd"),
        Field("sequence", "bcd"),
    ).compile()
    payload = bytes.fromhex("12 34 07 25 05")
    assert codec.decode(payload) == {
        "batch": 1234,
        "quantity": 7,
        "group": 25,
        "sequence": 5,
    }
    assert codec.encode(codec.decode(payload)) == payload


def test_uint24_big_endian() -> None:
    codec = Layout(Field("value", "uint24_be")).compile()
    assert codec.decode(bytes.fromhex("12 34 56"))["value"] == 0x123456
    assert codec.encode({"value": 0x123456}) == bytes.fromhex("12 34 56")


def test_little_endian_and_signed() -> None:
    codec = Layout(Field("a", "u16le"), Field("b", "i16be")).compile()
    payload = bytes.fromhex("34 12 FF FE")
    assert codec.decode(payload) == {"a": 0x1234, "b": -2}
    assert codec.encode({"a": 0x1234, "b": -2}) == payload


def test_float_roundtrip() -> None:
    codec = Layout(Field("temperature", "f32le")).compile()
    payload = codec.encode({"temperature": 12.5})
    assert math.isclose(codec.decode(payload)["temperature"], 12.5)


def test_ascii_fixed_width_pads_with_nul() -> None:
    codec = Layout(Field("name", "ascii", length=8)).compile()
    assert codec.encode({"name": "HELLO"}) == b"HELLO\x00\x00\x00"
    assert codec.decode(b"HELLO\x00\x00\x00") == {"name": "HELLO"}


def test_raw_bytes_exact_width() -> None:
    codec = Layout(Field("blob", "raw", length=3)).compile()
    assert codec.decode(b"\x01\x02\x03") == {"blob": b"\x01\x02\x03"}
    assert codec.encode({"blob": b"\x01\x02\x03"}) == b"\x01\x02\x03"
    with pytest.raises(EncodeError):
        codec.encode({"blob": b"\x01"})


def test_mac_roundtrip() -> None:
    codec = Layout(Field("address", "mac_address")).compile()
    payload = bytes.fromhex("02 00 00 00 00 01")
    assert codec.decode(payload)["address"] == "02:00:00:00:00:01"
    assert codec.encode({"address": "02:00:00:00:00:01"}) == payload


@pytest.mark.parametrize("kind,raw", [("u64be", 2**53 + 1), ("i64be", -(2**53 + 1))])
def test_scaled_64_bit_decode_rejects_integer_precision_loss(kind: str, raw: int) -> None:
    codec = Layout(Field("value", kind, scale=0.1)).compile()
    payload = raw.to_bytes(8, "big", signed=kind.startswith("i"))
    with pytest.raises(DecodeError, match="preserve integer precision"):
        codec.decode(payload)


def test_bias_cannot_silently_erase_integer_count() -> None:
    codec = Layout(Field("value", "u8", bias=1e30)).compile()
    with pytest.raises(DecodeError, match="preserve integer precision"):
        codec.decode(b"\x01")


def test_bias_cancellation_keeps_representable_small_counts() -> None:
    codec = Layout(Field("value", "u32be", scale=0.01, bias=-1000.0)).compile()
    payload = (2).to_bytes(4, "big")
    assert codec.decode(payload) == {"value": -999.98}
    assert codec.encode(codec.decode(payload)) == payload


@pytest.mark.parametrize(
    "kind,value,bias", [("u64be", 2**53 + 1, 1.0), ("i64be", -(2**53 + 1), -1.0)]
)
def test_scaled_integer_input_cannot_lose_precision(kind: str, value: int, bias: float) -> None:
    codec = Layout(Field("value", kind, bias=bias)).compile()
    with pytest.raises(EncodeError, match="input precision"):
        codec.encode({"value": value})


@pytest.mark.parametrize("value", [2**53, float(2**53)])
def test_inverse_bias_cannot_change_the_requested_physical_value(value: int | float) -> None:
    codec = Layout(Field("value", "u64be", bias=-1.0)).compile()
    with pytest.raises(EncodeError, match="input precision"):
        codec.encode({"value": value})


def test_ordinary_decimal_float_is_not_rejected_as_scaling_noise() -> None:
    codec = Layout(Field("value", "u8", scale=0.1)).compile()
    assert codec.encode({"value": 0.3}) == b"\x03"


def test_exact_large_scaled_count_remains_supported() -> None:
    codec = Layout(Field("value", "u64be", scale=0.5)).compile()
    payload = (2**54).to_bytes(8, "big")
    assert codec.encode({"value": 2**53}) == payload
    assert codec.encode(codec.decode(payload)) == payload


def test_scaled_integer_overflow_is_decode_error() -> None:
    codec = Layout(Field("value", "u64be", scale=1e308)).compile()
    with pytest.raises(DecodeError, match="preserve integer precision"):
        codec.decode((2**64 - 1).to_bytes(8, "big"))


def test_half_integer_is_not_scaling_noise_at_large_magnitudes() -> None:
    codec = Layout(Field("value", "u64be", bias=1.0)).compile()
    with pytest.raises(EncodeError, match="not exactly representable"):
        codec.encode({"value": 2**51 + 1.5})


def test_unknown_enum_value_roundtrips_as_integer() -> None:
    codec = Layout(Field("mode", "enum", values={0: "idle"})).compile()
    assert codec.encode(codec.decode(b"\xff")) == b"\xff"


def test_named_flags_canonicalize_unknown_bits() -> None:
    codec = Layout(Field("status", "flags", bits={"known": 0x01})).compile()
    assert codec.decode(b"\x81") == {"status": {"known": True}}
    assert codec.encode(codec.decode(b"\x81")) == b"\x01"
    assert codec.encode({"status": 0x81}) == b"\x81"


def test_boolean_decode_canonicalizes_nonzero_values() -> None:
    codec = Layout(Field("ready", "bool")).compile()
    assert codec.decode(b"\xff") == {"ready": True}
    assert codec.encode(codec.decode(b"\xff")) == b"\x01"


def test_reserved_bytes_are_zeroed_when_reencoding() -> None:
    codec = Layout(Field("value", "u8"), size=2).compile()
    assert codec.encode(codec.decode(b"\x07\xa5")) == b"\x07\x00"


def test_enum_decodes_label_and_encodes_label_or_raw() -> None:
    codec = Layout(Field("mode", "enum", values={1: "standby", 2: "active"})).compile()
    assert codec.decode(b"\x02") == {"mode": "active"}
    assert codec.decode(b"\x09") == {"mode": 9}
    assert codec.encode({"mode": "active"}) == b"\x02"
    assert codec.encode({"mode": 9}) == b"\x09"


def test_flags_roundtrip() -> None:
    codec = Layout(
        Field("status", "flags", bits={"confirmed": 0x08, "pending": 0x04, "failed": 0x01})
    ).compile()
    assert codec.decode(b"\x0c") == {
        "status": {"confirmed": True, "pending": True, "failed": False}
    }
    assert (
        codec.encode({"status": {"confirmed": True, "pending": True, "failed": False}}) == b"\x0c"
    )


def test_disjoint_bitfields_share_a_byte() -> None:
    codec = Layout(
        Field("high", "u8", mask=0xF0, shift=4),
        Field("low", "u8", offset=0, mask=0x0F),
    ).compile()
    assert codec.size == 1
    assert codec.decode(b"\x53") == {"high": 5, "low": 3}
    assert codec.encode({"high": 5, "low": 3}) == b"\x53"


def test_signed_masked_field_sign_extends() -> None:
    codec = Layout(Field("value", "i8", mask=0x0F)).compile()
    assert codec.decode(b"\x0f") == {"value": -1}
    assert codec.encode({"value": -1}) == b"\x0f"


def test_ambiguous_write_overlap_rejected() -> None:
    with pytest.raises(SchemaError, match="overlap"):
        Layout(Field("a", "u8"), Field("b", "u8", offset=0)).compile()


def test_scale_and_bias_roundtrip() -> None:
    codec = Layout(Field("voltage", "u16le", scale=0.01, bias=-1.0)).compile()
    payload = codec.encode({"voltage": 12.42})
    assert payload == (1342).to_bytes(2, "little")
    assert math.isclose(codec.decode(payload)["voltage"], 12.42)


def test_unrepresentable_scaled_integer_rejected() -> None:
    codec = Layout(Field("value", "u8", scale=0.5)).compile()
    with pytest.raises(EncodeError, match="not exactly representable"):
        codec.encode({"value": 1.25})


def test_invalid_bcd_rejected() -> None:
    codec = Layout(Field("value", "bcd")).compile()
    with pytest.raises(DecodeError, match="invalid BCD"):
        codec.decode(b"\xab")


def test_multibyte_bcd_roundtrip() -> None:
    codec = Layout(Field("code", "bcd", length=2)).compile()
    assert codec.decode(bytes.fromhex("12 34")) == {"code": 1234}
    assert codec.encode({"code": 1234}) == bytes.fromhex("12 34")


def test_short_payload_rejected() -> None:
    codec = Layout(Field("value", "u16be")).compile()
    with pytest.raises(DecodeError, match="requires 2"):
        codec.decode(b"\x01")


def test_trailing_payload_rejected_by_default() -> None:
    codec = Layout(Field("value", "u8")).compile()
    with pytest.raises(DecodeError, match="exactly 1"):
        codec.decode(b"\x01\x02")
    assert codec.decode(b"\x01\x02", strict=False) == {"value": 1}


def test_encode_requires_all_fields_by_default() -> None:
    codec = Layout(Field("a", "u8"), Field("b", "u8")).compile()
    with pytest.raises(EncodeError, match="Missing"):
        codec.encode({"a": 1})
    assert codec.encode({"a": 1}, require_all=False) == b"\x01\x00"


def test_encode_rejects_unknown_fields() -> None:
    codec = Layout(Field("a", "u8")).compile()
    with pytest.raises(EncodeError, match="Unknown"):
        codec.encode({"a": 1, "b": 2})


@pytest.mark.parametrize(
    "values", [None, 1, True, "", "value", b"", [], ["value"], [["value", 1]], (), set(), {"value"}]
)
@pytest.mark.parametrize("require_all", [True, False])
def test_encode_rejects_non_mapping_inputs(values: object, require_all: bool) -> None:
    codec = Layout(Field("value", "u8")).compile()
    with pytest.raises(EncodeError, match="must be a mapping"):
        codec.encode(values, require_all=require_all)  # type: ignore[arg-type]


def test_encode_mapping_validation_applies_to_empty_layouts_and_delegates() -> None:
    layout = Layout(Field("value", "u8"))
    with pytest.raises(EncodeError, match="must be a mapping"):
        Layout().compile().encode([])  # type: ignore[arg-type]
    with pytest.raises(EncodeError, match="must be a mapping"):
        layout.encode([], require_all=False)  # type: ignore[arg-type]
    with pytest.raises(EncodeError, match="must be a mapping"):
        Catalog({"status": layout}).encode("status", [], require_all=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("mapping_type", [dict, UserDict, MappingProxyType])
def test_encode_accepts_mapping_implementations(mapping_type) -> None:
    values = mapping_type({"value": 7})
    codec = Layout(Field("value", "u8")).compile()
    assert codec.encode(values) == b"\x07"
    assert codec.encode(values, require_all=False) == b"\x07"
    assert values == {"value": 7}


@pytest.mark.parametrize(
    "field",
    [
        Field("value", "u8"),
        Field("value", "i8"),
        Field("value", "u8", mask=0x0F),
        Field("value", "i8", mask=0x0F),
        Field("value", "enum", values={0: "zero"}),
        Field("value", "enum", values={0: "zero"}, mask=0x0F),
        Field("value", "flags", bits={"one": 1}),
        Field("value", "bcd"),
    ],
    ids=lambda field: f"{field.kind}-{field.mask}",
)
@pytest.mark.parametrize("sign", [-1, 1])
def test_huge_out_of_range_integers_raise_encode_error(field: Field, sign: int) -> None:
    with pytest.raises(EncodeError):
        Layout(field).encode({"value": sign * 10**5000})


def test_bcd_decimal_conversion_limits_raise_codec_errors() -> None:
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(640)
        codec = Layout(Field("value", "bcd", length=321)).compile()
        with pytest.raises(EncodeError, match="conversion limit"):
            codec.encode({"value": 10**640})
        with pytest.raises(DecodeError, match="conversion limit"):
            codec.decode(b"\x99" * 321)
    finally:
        sys.set_int_max_str_digits(previous)


def test_bool_encoding_is_strict() -> None:
    codec = Layout(Field("ready", "bool")).compile()
    assert codec.encode({"ready": True}) == b"\x01"
    assert codec.encode({"ready": 0}) == b"\x00"
    with pytest.raises(EncodeError, match="bool value"):
        codec.encode({"ready": "false"})


def test_flags_mapping_is_strict() -> None:
    codec = Layout(Field("status", "flags", bits={"ready": 0x01})).compile()
    with pytest.raises(EncodeError, match="flag 'ready'"):
        codec.encode({"status": {"ready": "false"}})


def test_u64_max_roundtrip_without_float_precision_loss() -> None:
    codec = Layout(Field("counter", "u64be")).compile()
    value = (1 << 64) - 1
    payload = codec.encode({"counter": value})
    assert codec.decode(payload) == {"counter": value}


def test_raw_integer_is_not_treated_as_zero_bytes() -> None:
    codec = Layout(Field("blob", "bytes", length=3)).compile()
    with pytest.raises(EncodeError, match="not integer length"):
        codec.encode({"blob": 3})


def test_little_endian_mac_roundtrip() -> None:
    codec = Layout(Field("address", "mac", byteorder="little")).compile()
    payload = bytes.fromhex("01 00 00 00 00 02")
    assert codec.decode(payload) == {"address": "02:00:00:00:00:01"}
    assert codec.encode({"address": "02:00:00:00:00:01"}) == payload


@pytest.mark.parametrize("payload", [1, True, "x", [1], None])
def test_decode_rejects_non_bytes_payloads(payload: object) -> None:
    with pytest.raises(DecodeError, match="Payload must be"):
        Layout(Field("value", "u8")).decode(payload)  # type: ignore[arg-type]


def test_decode_accepts_mutable_buffers_without_modifying_them() -> None:
    codec = Layout(Field("value", "u16le")).compile()
    payload = bytearray(b"\x34\x12")
    for buffer in (payload, memoryview(payload)):
        assert codec.decode(buffer) == {"value": 0x1234}
    assert payload == b"\x34\x12"


def test_released_memoryview_raises_decode_error() -> None:
    payload = memoryview(b"\x01")
    payload.release()
    with pytest.raises(DecodeError, match="memoryview"):
        Layout(Field("value", "u8")).decode(payload)


@pytest.mark.parametrize("unknown", [1, ("x",), None])
def test_unknown_field_keys_raise_encode_error(unknown: object) -> None:
    with pytest.raises(EncodeError, match="Unknown field"):
        Layout(Field("value", "u8")).encode({"value": 1, unknown: 0})  # type: ignore[dict-item]


def test_mixed_unknown_flag_keys_raise_encode_error() -> None:
    codec = Layout(Field("status", "flags", bits={"ready": 1})).compile()
    with pytest.raises(EncodeError, match="unknown flag"):
        codec.encode({"status": {1: True, "typo": False}})


def test_finite_float_inverse_scaling_overflow_is_encode_error() -> None:
    codec = Layout(Field("value", "f64be", scale=1e-308)).compile()
    with pytest.raises(EncodeError, match="overflows"):
        codec.encode({"value": 1e308})


def test_finite_float_scaling_overflow_is_decode_error() -> None:
    codec = Layout(Field("value", "f64be", scale=1e308)).compile()
    with pytest.raises(DecodeError, match="overflows"):
        codec.decode(bytes.fromhex("40 00 00 00 00 00 00 00"))


@pytest.mark.parametrize("kind", ["f32le", "f32be", "f64le", "f64be"])
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_explicit_nonfinite_float_values_remain_supported(kind: str, value: float) -> None:
    codec = Layout(Field("value", kind, scale=0.5, bias=1.0)).compile()
    decoded = codec.decode(codec.encode({"value": value}))["value"]
    assert math.isnan(decoded) if math.isnan(value) else decoded == value


@pytest.mark.parametrize("byteorder", ["big", "little"])
@pytest.mark.parametrize("separator", [":", "-"])
def test_mac_text_canonicalization(byteorder: str, separator: str) -> None:
    codec = Layout(Field("address", "mac", byteorder=byteorder)).compile()
    value = separator.join(["01", "23", "45", "67", "89", "aB"])
    raw = bytes.fromhex("01 23 45 67 89 AB")
    expected = raw[::-1] if byteorder == "little" else raw
    assert codec.encode({"address": value}) == expected
    assert codec.decode(expected) == {"address": "01:23:45:67:89:AB"}
    assert codec.encode(codec.decode(expected)) == expected
    for value in (raw, bytearray(raw), memoryview(raw), list(raw)):
        assert codec.encode({"address": value}) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "01:23:45:67:89",
        "01:23:45:67:89:AB:CD",
        "0123456789AB",
        "1:23:45:67:89:AB",
        "001:23:45:67:89:AB",
        "+1:23:45:67:89:AB",
        "-0:23:45:67:89:AB",
        "0x1:23:45:67:89:AB",
        " 1:23:45:67:89:AB",
        "01:23:45:67:89:AB ",
        "01:23:45:67:89:AB\n",
        "01:23-45:67:89:AB",
        "01:23:45:67:89:GG",
        "01:23:45:67:89:",
        "０1:23:45:67:89:AB",
        "1_0:23:45:67:89:AB",
        "100:23:45:67:89:AB",
        "01::23:45:67:89:AB",
    ],
)
def test_malformed_mac_text_is_rejected(value: str) -> None:
    with pytest.raises(EncodeError, match="invalid MAC address"):
        Layout(Field("address", "mac")).encode({"address": value})


@pytest.mark.parametrize("value", [None, 6, True, b"short", b"toolong", [256] * 6, object()])
def test_malformed_mac_buffers_are_rejected(value: object) -> None:
    with pytest.raises(EncodeError, match="MAC"):
        Layout(Field("address", "mac")).encode({"address": value})


def test_composite_flags_keep_any_set_bit_semantics() -> None:
    codec = Layout(Field("flags", "flags", bits={"pair": 0b0011, "other": 0b1100})).compile()
    decoded = {"flags": {"pair": True, "other": False}}
    assert codec.decode(b"\x81") == decoded
    assert codec.decode(b"\x82") == decoded
    assert codec.encode(decoded) == b"\x03"
    assert codec.encode({"flags": {"pair": 1}}) == b"\x03"
    assert codec.encode({"flags": 0x81}) == b"\x81"


def test_overlapping_composite_flags_can_canonicalize_in_multiple_steps() -> None:
    codec = Layout(Field("flags", "flags", bits={"first": 3, "second": 6})).compile()
    # Mapping values are views of masks. False is not a request to clear shared bits.
    assert codec.decode(b"\x01") == {"flags": {"first": True, "second": False}}
    assert codec.encode(codec.decode(b"\x01")) == b"\x03"
    assert codec.encode(codec.decode(b"\x03")) == b"\x07"
    assert codec.encode(codec.decode(b"\x07")) == b"\x07"


def test_masked_canonicalization_preserves_other_fields() -> None:
    codec = Layout(
        Field("flags", "flags", bits={"pair": 3}, mask=0xF0, shift=4),
        Field("ready", "bool", mask=0x0E, shift=1, offset=0),
        Field("bit", "u8", mask=1, offset=0),
        size=2,
    ).compile()
    assert codec.decode(b"\x9f\xff") == {"flags": {"pair": True}, "ready": True, "bit": 1}
    assert codec.encode(codec.decode(b"\x9f\xff")) == b"\x33\x00"
    assert codec.encode({"bit": 1}, require_all=False) == b"\x01\x00"


@pytest.mark.parametrize("byteorder", ["big", "little"])
@pytest.mark.parametrize("kind", ["enum", "flags"])
def test_enum_and_flags_full_width_boundaries(kind: str, byteorder: str) -> None:
    maximum = 2**64 - 1
    field = (
        Field("value", kind, length=8, byteorder=byteorder, values={maximum: "max"})
        if kind == "enum"
        else Field("value", kind, length=8, byteorder=byteorder, bits={"all": maximum})
    )
    codec = Layout(field).compile()
    for value in (0, 1, maximum):
        assert codec.encode({"value": value}) == value.to_bytes(8, byteorder)
    assert codec.encode(codec.decode(b"\xff" * 8)) == b"\xff" * 8
    for value in (-1, maximum + 1):
        with pytest.raises(EncodeError, match="does not fit"):
            codec.encode({"value": value})


@pytest.mark.parametrize("kind", ["enum", "flags", "bool"])
def test_masked_special_kinds_and_limits(kind: str) -> None:
    options = (
        {"values": {15: "max"}}
        if kind == "enum"
        else {"bits": {"all": 15}}
        if kind == "flags"
        else {}
    )
    codec = Layout(Field("value", kind, mask=0xF0, shift=4, **options)).compile()
    expected = "max" if kind == "enum" else {"all": True} if kind == "flags" else True
    assert codec.decode(b"\xff") == {"value": expected}
    assert codec.encode({"value": expected}) == (b"\x10" if kind == "bool" else b"\xf0")
    for value in (-1, 16):
        with pytest.raises(EncodeError):
            codec.encode({"value": value})


@pytest.mark.parametrize("kind", ["f32be", "f32le", "f64be", "f64le"])
def test_float_boundaries_and_signed_zero(kind: str) -> None:
    binary32 = kind.startswith("f32")
    maximum = float.fromhex("0x1.fffffep+127" if binary32 else "0x1.fffffffffffffp+1023")
    normal = float.fromhex("0x1p-126" if binary32 else "0x1p-1022")
    subnormal = float.fromhex("0x1p-149" if binary32 else "0x1p-1074")
    fmt = (">" if kind.endswith("be") else "<") + ("f" if binary32 else "d")
    codec = Layout(Field("value", kind)).compile()
    for value in (0.0, -0.0, normal, -normal, subnormal, -subnormal, maximum, -maximum):
        expected = struct.pack(fmt, value)
        assert codec.encode({"value": value}) == expected
        assert codec.encode(codec.decode(expected)) == expected
    with pytest.raises(EncodeError, match="too large|does not fit"):
        codec.encode({"value": 10**400})
    if binary32:
        with pytest.raises(EncodeError, match="does not fit"):
            codec.encode({"value": 2**128})
        assert codec.encode({"value": subnormal / 4}) == b"\x00" * 4


@pytest.mark.parametrize("width", [1, 2, 8])
def test_bcd_boundaries(width: int) -> None:
    codec = Layout(Field("value", "bcd", length=width)).compile()
    maximum = 10 ** (width * 2) - 1
    assert codec.decode(b"\x00" * width) == {"value": 0}
    assert codec.encode({"value": maximum}) == b"\x99" * width
    assert codec.encode(codec.decode(b"\x99" * width)) == b"\x99" * width
    for value in (-1, maximum + 1, 0.5):
        with pytest.raises(EncodeError):
            codec.encode({"value": value})


@pytest.mark.parametrize("byte", [0x0A, 0xA0, 0xFF])
def test_bad_bcd_nibbles_anywhere_are_rejected(byte: int) -> None:
    with pytest.raises(DecodeError, match="invalid BCD"):
        Layout(Field("value", "bcd", length=2)).decode(bytes([0, byte]))


def test_ascii_embedded_nuls_and_padding_are_canonical() -> None:
    codec = Layout(Field("text", "ascii", length=5)).compile()
    assert codec.decode(b"a\x00b\x00\x00") == {"text": "a\x00b"}
    assert codec.encode({"text": "a\x00b\x00"}) == b"a\x00b\x00\x00"
    assert codec.encode(codec.decode(b"\x00" * 5)) == b"\x00" * 5
    for value in ("é", "abcdef", b"abc", None):
        with pytest.raises(EncodeError):
            codec.encode({"text": value})
    with pytest.raises(DecodeError, match="invalid ASCII"):
        codec.decode(b"a\xffb\x00\x00")


@pytest.mark.parametrize("value", ["abc", None, [256], [-1], True])
def test_malformed_raw_values_raise_encode_error(value: object) -> None:
    with pytest.raises(EncodeError):
        Layout(Field("raw", "bytes", length=1)).encode({"raw": value})


def test_omitted_fields_leave_wire_zero_without_physical_defaults() -> None:
    codec = Layout(
        Field("scaled", "u8", bias=20),
        Field("mode", "enum", values={0: "idle"}),
    ).compile()
    assert codec.encode({}, require_all=False) == b"\x00\x00"
    assert codec.decode(b"\x00\x00") == {"scaled": 20, "mode": "idle"}
