from __future__ import annotations

import json

import pytest

from structwire import (
    Field,
    Layout,
    SchemaError,
    format_mac_address,
    format_record,
    format_value,
    layout_from_mapping,
)


@pytest.mark.parametrize("attribute", ["scale", "bias"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_scaling_is_a_schema_error(attribute: str, value: float) -> None:
    with pytest.raises(SchemaError, match="finite"):
        Field("value", "u16le", **{attribute: value})  # type: ignore[arg-type]


def test_explicit_offsets_create_gaps() -> None:
    codec = Layout(Field("head", "u8"), Field("tail", "u8", offset=3)).compile()
    assert codec.size == 4
    assert codec.encode({"head": 1, "tail": 2}) == b"\x01\x00\x00\x02"


def test_duplicate_names_rejected() -> None:
    with pytest.raises(SchemaError):
        Layout(Field("same", "u8"), Field("same", "u8"))


def test_noncontiguous_mask_rejected() -> None:
    with pytest.raises(SchemaError, match="contiguous"):
        Field("bad", "u8", mask=0b1010, shift=1)


def test_describe_reports_resolved_offsets() -> None:
    description = Layout(Field("a", "u8"), Field("b", "u16le"), name="demo").compile().describe()
    assert description["name"] == "demo"
    assert description["size"] == 3
    assert description["fields"][1]["offset"] == 1


def test_formatting_helpers_render_readable_values() -> None:
    assert format_mac_address(bytes.fromhex("02 00 00 00 00 01")) == "02:00:00:00:00:01"
    assert (
        format_mac_address(bytes.fromhex("01 00 00 00 00 02"), byteorder="little")
        == "02:00:00:00:00:01"
    )
    assert format_value(b"\x12\x34\x56") == "12 34 56"
    assert format_value(b"") == "<empty>"
    assert format_record({"raw": b"\x01", "nested": {"x": b"\x02"}}) == {
        "raw": "01",
        "nested": {"x": "02"},
    }


def test_mask_rejected_for_non_numeric_byte_fields() -> None:
    with pytest.raises(SchemaError, match="mask is not valid"):
        Field("text", "ascii", length=4, mask=0xFF)


def test_enum_values_must_fit_storage() -> None:
    with pytest.raises(SchemaError, match="enum value"):
        Field("mode", "enum", values={256: "impossible"})


def test_huge_enum_key_raises_schema_error() -> None:
    with pytest.raises(SchemaError, match="enum value"):
        Field("mode", "enum", values={10**5000: "impossible"})


def test_flag_masks_must_fit_storage() -> None:
    with pytest.raises(SchemaError, match="flag mask"):
        Field("flags", "flags", bits={"too_large": 0x100})


def test_describe_exposes_console_metadata() -> None:
    description = (
        Layout(
            Field(
                "mode",
                "enum",
                values={0: "idle", 1: "active"},
                unit="state",
                description="Current operating mode",
            ),
            name="status",
            description="Status payload",
        )
        .compile()
        .describe()
    )
    assert description["description"] == "Status payload"
    field = description["fields"][0]
    assert field["values"] == {0: "idle", 1: "active"}
    assert field["unit"] == "state"


@pytest.mark.parametrize("attribute", ["offset", "length", "shift", "mask"])
@pytest.mark.parametrize("value", [True, 1.5, "1"])
def test_python_field_integer_parameters_are_strict(attribute: str, value: object) -> None:
    with pytest.raises(SchemaError, match="must be an integer"):
        Field("value", "u8", **{attribute: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, 1.5, "1"])
def test_layout_size_is_an_integer(value: object) -> None:
    with pytest.raises(SchemaError, match="must be an integer"):
        Layout(Field("value", "u8"), size=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, 1.5, "1"])
def test_python_enum_schema_keys_do_not_truncate(value: object) -> None:
    with pytest.raises(SchemaError, match="enum key must be an integer"):
        Field("mode", "enum", values={value: "active"})  # type: ignore[dict-item]


def test_python_flag_masks_do_not_truncate() -> None:
    with pytest.raises(SchemaError, match="flag mask must be an integer"):
        Field("status", "flags", bits={"active": 1.5})  # type: ignore[dict-item]


@pytest.mark.parametrize("attribute", ["scale", "bias"])
def test_boolean_scaling_is_rejected(attribute: str) -> None:
    with pytest.raises(SchemaError, match="finite number"):
        Field("value", "u8", **{attribute: True})  # type: ignore[arg-type]


def test_shift_requires_a_mask() -> None:
    with pytest.raises(SchemaError, match="shift requires a mask"):
        Field("value", "u8", shift=4)


def test_shift_cannot_be_none() -> None:
    with pytest.raises(SchemaError, match="shift must be an integer"):
        Field("value", "u8", shift=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind,width", [("u16le", 2), ("f32be", 4)])
def test_length_cannot_override_fixed_width(kind: str, width: int) -> None:
    with pytest.raises(SchemaError, match="exactly"):
        Field("value", kind, length=width + 1)
    assert Field("value", kind, length=width).width == width


@pytest.mark.parametrize("attribute", ["values", "bits"])
@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_field_tables_must_be_mappings(attribute: str, value: object) -> None:
    with pytest.raises(SchemaError, match="must be mappings"):
        Field("value", "u8", **{attribute: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("attribute", ["kind", "description", "unit"])
def test_field_text_parameters_must_be_strings(attribute: str) -> None:
    arguments = {"name": "value", "kind": "u8", attribute: []}
    with pytest.raises(SchemaError, match="must be a string"):
        Field(**arguments)  # type: ignore[arg-type]


def test_layout_description_must_be_a_string() -> None:
    with pytest.raises(SchemaError, match="description must be a string"):
        Layout(description=[])  # type: ignore[arg-type]


def test_byteorder_rejects_unhashable_values_with_schema_error() -> None:
    with pytest.raises(SchemaError, match="byteorder"):
        Field("value", "u8", byteorder=[])  # type: ignore[arg-type]


def test_field_copies_and_freezes_enum_tables() -> None:
    values = {0: "idle"}
    field = Field("mode", "enum", values=values)
    values[0] = "changed"
    assert Layout(field).decode(b"\x00") == {"mode": "idle"}
    with pytest.raises(TypeError):
        field.values[0] = "changed"  # type: ignore[index]


def test_mac_formatter_rejects_integer_lengths() -> None:
    with pytest.raises(ValueError, match="must be bytes"):
        format_mac_address(6)  # type: ignore[arg-type]


def test_description_roundtrips_through_json_and_loader() -> None:
    codec = Layout(
        Field("counter", "u16le"),
        Field("mode", "enum", values={1: "active"}),
        Field("temperature", "i8", scale=0.5, bias=-1.0),
        Field("status", "flags", bits={"ready": 1}),
        name="status",
        size=8,
    ).compile()
    restored = layout_from_mapping(json.loads(json.dumps(codec.describe()))).compile()
    assert restored.describe() == codec.describe()
    values = {"counter": 0x1234, "mode": "active", "temperature": 2.0, "status": {"ready": True}}
    assert restored.encode(values) == codec.encode(values)
    description = codec.describe()
    description["fields"][1]["values"][1] = "changed"
    assert codec.decode(codec.encode(values))["mode"] == "active"
