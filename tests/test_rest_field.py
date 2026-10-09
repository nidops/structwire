from __future__ import annotations

import json

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from structwire import (
    Catalog,
    DecodeError,
    EncodeError,
    Field,
    Layout,
    SchemaError,
    catalog_from_mapping,
    layout_from_mapping,
    layout_from_yaml,
)

TAIL_RECORD = Layout(
    Field("tag", "u8"),
    Field("sequence", "u16be"),
    Field("data", "bytes", length="rest"),
    name="tail_record",
)


def test_rest_bytes_take_remaining_payload() -> None:
    codec = TAIL_RECORD.compile()
    payload = bytes.fromhex("05 01 02 41 42 43")
    assert codec.decode(payload) == {"tag": 0x05, "sequence": 0x0102, "data": b"ABC"}
    assert codec.encode(codec.decode(payload)) == payload


def test_rest_bytes_may_be_empty() -> None:
    codec = TAIL_RECORD.compile()
    assert codec.decode(bytes.fromhex("05 01 02"))["data"] == b""
    assert codec.encode({"tag": 0x05, "sequence": 0x0102, "data": b""}) == bytes.fromhex("05 01 02")


@given(st.binary(max_size=64))
def test_rest_bytes_roundtrip(data: bytes) -> None:
    codec = TAIL_RECORD.compile()
    payload = codec.encode({"tag": 0x22, "sequence": 0x1234, "data": data})
    assert payload == bytes.fromhex("22 12 34") + data
    assert codec.decode(payload)["data"] == data


def test_rest_ascii_has_no_padding_and_preserves_trailing_nul() -> None:
    codec = Layout(Field("kind", "u8"), Field("text", "ascii", length="rest")).compile()
    assert codec.encode({"kind": 1, "text": "hello"}) == b"\x01hello"
    assert codec.decode(b"\x01hi\x00\x00") == {"kind": 1, "text": "hi\x00\x00"}
    assert codec.encode(codec.decode(b"\x01hi\x00\x00")) == b"\x01hi\x00\x00"


def test_rest_ascii_rejects_non_ascii_payload() -> None:
    codec = Layout(Field("text", "ascii", length="rest")).compile()
    with pytest.raises(DecodeError, match="ASCII"):
        codec.decode(b"\xff")


def test_variable_layout_reports_minimum_size() -> None:
    codec = TAIL_RECORD.compile()
    assert codec.variable
    assert codec.size == 3
    assert not Layout(Field("a", "u8")).compile().variable


def test_variable_layout_rejects_short_payload() -> None:
    with pytest.raises(DecodeError, match="at least 3"):
        TAIL_RECORD.compile().decode(b"\x05\x01")


@pytest.mark.parametrize("strict", [True, False])
def test_strict_has_no_effect_on_variable_layout(strict: bool) -> None:
    decoded = TAIL_RECORD.compile().decode(bytes.fromhex("05 01 02 01 02"), strict=strict)
    assert decoded["data"] == b"\x01\x02"


def test_rest_field_accepts_bytes_like_values_and_payloads() -> None:
    codec = TAIL_RECORD.compile()
    payload = codec.encode({"tag": 1, "sequence": 2, "data": bytearray(b"\xaa")})
    assert payload == b"\x01\x00\x02\xaa"
    assert codec.decode(memoryview(payload))["data"] == b"\xaa"


def test_rest_bytes_reject_integer_value() -> None:
    with pytest.raises(EncodeError, match="integer length"):
        TAIL_RECORD.compile().encode({"tag": 1, "sequence": 2, "data": 3})


def test_omitted_rest_field_encodes_fixed_part_only() -> None:
    codec = TAIL_RECORD.compile()
    assert codec.encode({"tag": 0x05}, require_all=False) == b"\x05\x00\x00"


def test_rest_field_after_explicit_gap() -> None:
    codec = Layout(Field("head", "u8"), Field("tail", "bytes", length="rest", offset=3)).compile()
    assert codec.size == 3
    assert codec.encode({"head": 1, "tail": b"\x09"}) == b"\x01\x00\x00\x09"
    assert codec.decode(b"\x01\x00\x00\x09\x08") == {"head": 1, "tail": b"\x09\x08"}


def test_field_declared_after_rest_may_precede_it_by_offset() -> None:
    codec = Layout(
        Field("tail", "bytes", length="rest", offset=1),
        Field("head", "u8", offset=0),
    ).compile()
    assert codec.decode(b"\x07\x01\x02") == {"tail": b"\x01\x02", "head": 7}


def test_size_equal_to_rest_offset_is_accepted() -> None:
    assert Layout(Field("a", "u8"), Field("b", "bytes", length="rest"), size=1).compile().size == 1


@pytest.mark.parametrize(
    "layout,match",
    [
        (
            lambda: Layout(Field("a", "bytes", length="rest"), Field("b", "u8")),
            "must be the last field",
        ),
        (
            lambda: Layout(
                Field("a", "bytes", length="rest"), Field("b", "ascii", length="rest", offset=4)
            ),
            "only one 'rest' field",
        ),
        (
            lambda: Layout(Field("a", "u8"), Field("b", "bytes", length="rest"), size=4),
            "starts at byte 1",
        ),
    ],
)
def test_invalid_rest_layouts_raise_schema_error(layout, match: str) -> None:
    with pytest.raises(SchemaError, match=match):
        layout().compile()


@pytest.mark.parametrize("kind", ["u8", "u16be", "bcd", "mac", "enum", "flags", "bool", "f32le"])
def test_rest_length_only_valid_for_ascii_and_bytes(kind: str) -> None:
    with pytest.raises(SchemaError, match="only valid for ascii/bytes"):
        Field("value", kind, length="rest")


def test_rest_field_properties() -> None:
    field = Field("data", "raw", length="rest")
    assert field.variable
    assert field.width == 0
    assert not Field("data", "raw", length=2).variable


def test_mapping_loader_accepts_rest_length() -> None:
    layout = layout_from_mapping(
        {
            "fields": [
                {"name": "tag", "type": "uint8"},
                {"name": "data", "type": "raw", "length": "rest"},
            ]
        }
    )
    assert layout.compile().decode(b"\x62\x01") == {"tag": 0x62, "data": b"\x01"}


def test_yaml_loader_accepts_rest_length(tmp_path) -> None:
    path = tmp_path / "layout.yaml"
    path.write_text(
        "fields:\n  - {name: tag, type: u8}\n  - {name: text, type: ascii, length: rest}\n",
        encoding="utf-8",
    )
    assert layout_from_yaml(path).compile().decode(b"\x01ok") == {"tag": 1, "text": "ok"}


def test_describe_reports_rest_and_reloads() -> None:
    description = TAIL_RECORD.compile().describe()
    assert description["size"] == 3
    assert description["fields"][2]["length"] == "rest"
    reloaded = layout_from_mapping(json.loads(json.dumps(description))).compile()
    assert reloaded.describe() == description
    assert reloaded.variable


def test_catalog_with_variable_layout() -> None:
    catalog = catalog_from_mapping(
        yaml.safe_load(
            """
            codecs:
              tail_record:
                fields:
                  - {name: sequence, type: uint16_be}
                  - {name: data, type: raw, length: rest}
            """
        )
    )
    assert catalog.decode("tail_record", b"\x01\x02\x01\x02") == {
        "sequence": 0x0102,
        "data": b"\x01\x02",
    }
    assert (
        Catalog({"tail_record": TAIL_RECORD}).encode(
            "tail_record", {"tag": 1, "sequence": 2, "data": b"\x03"}
        )
        == b"\x01\x00\x02\x03"
    )


def test_only_rest_field_has_zero_minimum_size() -> None:
    codec = Layout(Field("tail", "bytes", length="rest")).compile()
    assert codec.variable
    assert codec.size == 0
    assert codec.decode(b"") == {"tail": b""}
    assert codec.encode({"tail": b""}) == b""
    assert codec.encode({"tail": b"\x00\xff"}) == b"\x00\xff"


@given(st.text(alphabet=st.characters(min_codepoint=0, max_codepoint=127), max_size=64))
def test_ascii_rest_roundtrip_preserves_all_ascii_octets(text: str) -> None:
    codec = Layout(Field("tail", "ascii", length="rest")).compile()
    payload = text.encode("ascii")
    assert codec.decode(payload) == {"tail": text}
    assert codec.encode(codec.decode(payload)) == payload


def test_fixed_width_ascii_still_removes_padding() -> None:
    codec = Layout(Field("text", "ascii", length=4)).compile()
    assert codec.decode(b"A\x00\x00\x00") == {"text": "A"}
    assert codec.encode({"text": "A"}) == b"A\x00\x00\x00"


def test_reordered_tail_encoding_and_decoding() -> None:
    codec = Layout(
        Field("tail", "bytes", length="rest", offset=2),
        Field("header", "u16be", offset=0),
    ).compile()
    payload = b"\x12\x34\xaa\xbb"
    assert codec.encode({"header": 0x1234, "tail": b"\xaa\xbb"}) == payload
    assert codec.decode(payload) == {"tail": b"\xaa\xbb", "header": 0x1234}


def test_masked_header_and_tail_roundtrip() -> None:
    codec = Layout(
        Field("upper", "u8", mask=0xF0, shift=4),
        Field("lower", "u8", offset=0, mask=0x0F),
        Field("tail", "bytes", length="rest"),
    ).compile()
    payload = b"\xa5\x00\xff"
    assert codec.decode(payload) == {"upper": 10, "lower": 5, "tail": b"\x00\xff"}
    assert codec.encode(codec.decode(payload)) == payload


def test_rest_cannot_overlap_masked_header() -> None:
    with pytest.raises(SchemaError, match="must be the last field"):
        Layout(
            Field("upper", "u8", mask=0xF0, shift=4, offset=0),
            Field("tail", "bytes", length="rest", offset=0),
        ).compile()


@pytest.mark.parametrize("invalid", [True, False, -1, 0, 1.5, "invalid", [], {}])
def test_rest_length_still_validates_invalid_lengths(invalid: object) -> None:
    with pytest.raises(SchemaError):
        Field("tail", "bytes", length=invalid)  # type: ignore[arg-type]


def test_missing_required_rest_field_is_error() -> None:
    codec = Layout(Field("head", "u8"), Field("tail", "bytes", length="rest")).compile()
    with pytest.raises(EncodeError, match="Missing field"):
        codec.encode({"head": 1})


def test_variable_ascii_rejects_unicode_on_encode() -> None:
    codec = Layout(Field("text", "ascii", length="rest")).compile()
    with pytest.raises(EncodeError, match="ASCII"):
        codec.encode({"text": "caf\u00e9"})


def test_non_contiguous_view_can_be_decoded() -> None:
    codec = Layout(Field("tail", "bytes", length="rest")).compile()
    payload = memoryview(b"\x01\xaa\x02\xbb")[::2]
    assert codec.decode(payload) == {"tail": b"\x01\x02"}


def test_fixed_layout_exact_size_semantics_unchanged() -> None:
    codec = Layout(Field("head", "u8")).compile()
    with pytest.raises(DecodeError, match="expected exactly"):
        codec.decode(b"\x01\x02")
    assert codec.decode(b"\x01\x02", strict=False) == {"head": 1}
