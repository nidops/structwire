"""Regression coverage for the numerical and schema contracts."""

import math
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from structwire import (
    Catalog,
    DecodeError,
    EncodeError,
    Field,
    Layout,
    SchemaError,
    layout_from_yaml,
)


@pytest.mark.parametrize("kind", ["u8", "i24le", "u64le", "bcd"])
@pytest.mark.parametrize(
    "value", [3.0000000000001, math.nextafter(3.0, 4.0), math.nextafter(3.0, 2.0)]
)
def test_unscaled_fraction_is_never_rounded(kind, value):
    with pytest.raises(EncodeError, match="not exactly representable"):
        Layout(Field("v", kind)).encode({"v": value})


@pytest.mark.parametrize(
    "field",
    [
        Field("v", "u8"),
        Field("v", "f32le"),
        Field("v", "bcd"),
        Field("v", "enum", values={1: "one"}),
        Field("v", "flags", bits={"one": 1}),
    ],
)
@pytest.mark.parametrize("value", [True, False])
def test_boolean_is_not_a_numeric_count(field, value):
    with pytest.raises(EncodeError):
        Layout(field).encode({"v": value})


@pytest.mark.parametrize("value", [Decimal("3"), Fraction(3, 1), "3", None])
def test_numerical_types_are_explicit(value):
    with pytest.raises(EncodeError):
        Layout(Field("v", "u8")).encode({"v": value})


@pytest.mark.parametrize(
    "kind,width,signed,order",
    [
        ("u24le", 3, False, "little"),
        ("i24be", 3, True, "big"),
        ("u64le", 8, False, "little"),
        ("u64be", 8, False, "big"),
        ("i64le", 8, True, "little"),
        ("i64be", 8, True, "big"),
    ],
)
@pytest.mark.parametrize("scale,bias", [(0.5, 0.0), (-0.1, 1000.0), (0.001, -1000.0)])
def test_raw_counts_keep_storage_limits(kind, width, signed, order, scale, bias):
    codec = Layout(Field("v", kind, scale=scale, bias=bias)).compile()
    lo = -(1 << (8 * width - 1)) if signed else 0
    hi = (1 << (8 * width - int(signed))) - 1
    for count in (lo, lo + 1, 0, hi - 1, hi):
        payload = count.to_bytes(width, order, signed=signed)
        assert codec.decode(payload, scaled=False) == {"v": count}
        assert codec.encode({"v": count}, scaled=False) == payload
    for count in (lo - 1, hi + 1):
        with pytest.raises(EncodeError):
            codec.encode({"v": count}, scaled=False)


def test_precision_error_distinguishes_valid_wire_from_bad_data():
    from structwire import PrecisionError

    codec = Layout(Field("v", "u64le", scale=0.5)).compile()
    wire = (2**64 - 1).to_bytes(8, "little")
    with pytest.raises(PrecisionError, match="scaled=False") as raised:
        codec.decode(wire)
    assert isinstance(raised.value, DecodeError)
    with pytest.raises(DecodeError) as malformed:
        codec.decode(b"")
    assert not isinstance(malformed.value, PrecisionError)
    count = codec.decode(wire, scaled=False)["v"]
    assert Decimal(count) * Decimal("0.5") == Decimal("9223372036854775807.5")


def test_raw_mode_forwards_through_layout_and_catalog():
    layout = Layout(Field("v", "u64le", scale=0.5), name="sample")
    values = {"v": 2**64 - 1}
    wire = b"\xff" * 8
    catalog = Catalog({"sample": layout})
    assert layout.encode(values, scaled=False) == wire
    assert layout.decode(wire, scaled=False) == values
    assert catalog.encode("sample", values, scaled=False) == wire
    assert catalog.decode("sample", wire, scaled=False) == values


def test_raw_mode_keeps_masks_bcd_float_and_tail_semantics():
    codec = Layout(
        Field("hi", "i8", mask=0xF0, shift=4, scale=0.5),
        Field("lo", "u8", offset=0, mask=0xF),
        Field("b", "bcd", scale=0.1),
        Field("f", "f32le", scale=2.0, bias=1),
        Field("tail", "ascii", length="rest"),
    ).compile()
    raw = {"hi": -2, "lo": 3, "b": 12, "f": 1.5, "tail": "A\0"}
    wire = b"\xe3\x12\x00\x00\xc0\x3fA\0"
    assert codec.encode(raw, scaled=False) == wire
    assert codec.decode(wire, scaled=False) == raw
    assert codec.decode(wire) == {
        "hi": -1.0,
        "lo": 3,
        "b": 1.2000000000000002,
        "f": 4.0,
        "tail": "A\0",
    }
    with pytest.raises(DecodeError, match="BCD"):
        Layout(Field("v", "bcd", scale=0.5)).decode(b"\xff", scaled=False)


@settings(max_examples=200, derandomize=True, deadline=None)
@given(st.integers(0, 2**64 - 1))
def test_raw_u64_property(count):
    codec = Layout(Field("v", "u64le", scale=-0.1, bias=2.0)).compile()
    wire = count.to_bytes(8, "little")
    assert codec.encode(codec.decode(wire, scaled=False), scaled=False) == wire


@pytest.mark.parametrize("name", [" x", "x ", "\tx", "x\n"])
def test_identifiers_are_rejected_instead_of_trimmed(name):
    for factory in (
        lambda: Field(name, "u8"),
        lambda: Layout(name=name),
        lambda: Catalog({name: Layout()}),
        lambda: Field("f", "flags", bits={name: 1}),
    ):
        with pytest.raises(SchemaError, match="whitespace"):
            factory()


@pytest.mark.parametrize("bits", [{"a": 1, "b": 1}, {"a": 3, "b": 6}, {"a": 3, "b": 1}])
def test_overlapping_flag_masks_rejected(bits):
    with pytest.raises(SchemaError, match="overlap"):
        Field("v", "flags", bits=bits)


def yaml_codec(tmp_path, text):
    path = tmp_path / "schema.yaml"
    path.write_text(text, encoding="utf-8")
    return layout_from_yaml(path).compile()


def test_yaml_merges_allow_explicit_override_and_reused_anchors(tmp_path):
    codec = yaml_codec(
        tmp_path,
        """fields:
  - &base {name: a, type: u8}
  - &derived {<<: *base, name: b, type: u16le}
  - {<<: *derived, name: c}
""",
    )
    assert codec.decode(b"\x01\x02\x00\x03\x00") == {"a": 1, "b": 2, "c": 3}


def test_yaml_merge_sequence_keeps_first_mapping_precedence(tmp_path):
    codec = yaml_codec(tmp_path, "fields: [{<<: [{name: a, type: u8}, {type: u16le}]}]")
    assert codec.size == 1


@pytest.mark.parametrize(
    "text",
    [
        "fields: [{<<: {name: a, type: u8}, name: b, name: c}]",
        "fields: [{<<: {name: a, type: u8, type: u16le}}]",
        "fields: [{<<: {name: a, type: u8}, <<: {name: b}}]",
        "fields: [{name: a, type: enum, values: {true: on, 1: one}}]",
    ],
)
def test_yaml_explicit_duplicates_are_not_lost_by_merge(tmp_path, text):
    with pytest.raises(SchemaError, match="Duplicate YAML key.*line"):
        yaml_codec(tmp_path, text)


@pytest.mark.parametrize("number", ["010", "00", "-010", "1:20", "0_10"])
def test_yaml_ambiguous_numeric_notation_is_rejected(tmp_path, number):
    with pytest.raises(SchemaError, match="ambiguous YAML integer"):
        yaml_codec(tmp_path, f"fields: [{{name: a, type: u8, offset: {number}}}]")


@pytest.mark.parametrize("number", ["10", "0x0a", '"0o12"', '"0b1010"'])
def test_yaml_explicit_integer_interpretation(tmp_path, number):
    assert yaml_codec(tmp_path, f"fields: [{{name: a, type: u8, offset: {number}}}]").size == 11


def test_yaml_boolean_label_has_actionable_message(tmp_path):
    with pytest.raises(SchemaError, match="quote.*on.*off"):
        yaml_codec(tmp_path, "fields: [{name: a, type: enum, values: {0: off, 1: on}}]")


def test_compiled_codec_is_reusable_across_threads():
    codec = Layout(
        Field("count", "u64le", scale=0.5), Field("tail", "bytes", length="rest")
    ).compile()

    def work(i):
        raw = {"count": 2**64 - 1 - i, "tail": bytes([i])}
        assert codec.decode(codec.encode(raw, scaled=False), scaled=False) == raw
        assert codec.decode(codec.encode({"count": i * 0.5, "tail": b"x"})) == {
            "count": i * 0.5,
            "tail": b"x",
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(64)))
    assert "variable=True" in repr(codec)


def test_schema_hashing_is_not_promised():
    with pytest.raises(TypeError):
        hash(Field("v", "u8"))
    with pytest.raises(TypeError):
        hash(Layout(Field("v", "u8")))
