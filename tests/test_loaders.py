from __future__ import annotations

import pytest
import yaml

from structwire import (
    Catalog,
    Field,
    Layout,
    SchemaError,
    catalog_from_mapping,
    catalog_from_yaml,
    layout_from_mapping,
    layout_from_yaml,
)


def test_mapping_loader_accepts_schema_aliases() -> None:
    layout = layout_from_mapping(
        {
            "name": "status",
            "fields": [
                {"name": "upper_nibble", "type": "uint8", "bitmask": "0xF0", "bitshift": 4},
                {"name": "lower_nibble", "type": "uint8", "offset": 0, "bitmask": "0x0F"},
            ],
        }
    )
    codec = layout.compile()
    assert codec.decode(b"\x53") == {"upper_nibble": 5, "lower_nibble": 3}


def test_mapping_loader_parses_enum_hex_keys() -> None:
    codec = layout_from_mapping(
        {
            "fields": [
                {
                    "name": "mode",
                    "type": "enum",
                    "values": {"0x01": "idle", "0x02": "active"},
                }
            ]
        }
    ).compile()
    assert codec.decode(b"\x02") == {"mode": "active"}


def test_mapping_loader_accepts_hex_offsets() -> None:
    codec = layout_from_mapping(
        {
            "fields": [
                {"name": "head", "type": "uint8"},
                {"name": "tail", "type": "uint8", "offset": "0x03"},
            ]
        }
    ).compile()
    assert codec.size == 4
    assert codec.encode({"head": 1, "tail": 2}) == b"\x01\x00\x00\x02"


def test_catalog_loader_compiles_named_codecs() -> None:
    catalog = catalog_from_mapping(
        {
            "version": 1,
            "codecs": {
                "status": {
                    "size": 4,
                    "fields": [
                        {
                            "name": "mode",
                            "type": "enum",
                            "values": {"0x00": "idle", "0x01": "active"},
                        },
                        {"name": "temperature", "type": "i16le", "scale": 0.1, "unit": "degC"},
                    ],
                }
            },
        }
    )
    assert isinstance(catalog, Catalog)
    assert catalog.names == ("status",)
    assert catalog["status"].size == 4
    assert catalog["status"].fields[1].unit == "degC"
    assert catalog.decode("status", b"\x01\xfa\x00\x00") == {
        "mode": "active",
        "temperature": 25.0,
    }


def test_catalog_rejects_name_mismatch() -> None:
    with pytest.raises(SchemaError, match="conflicts"):
        catalog_from_mapping(
            {
                "codecs": {
                    "outer": {
                        "name": "inner",
                        "fields": [{"name": "x", "type": "u8"}],
                    }
                }
            }
        )


def test_declared_size_can_add_trailing_reserved_bytes() -> None:
    codec = layout_from_mapping(
        {
            "name": "small",
            "size": 4,
            "fields": [{"name": "x", "type": "u8"}],
        }
    ).compile()
    assert codec.size == 4
    assert codec.encode({"x": 7}) == b"\x07\x00\x00\x00"


def test_declared_size_cannot_truncate_fields() -> None:
    with pytest.raises(SchemaError, match="fields require at least"):
        layout_from_mapping(
            {
                "name": "bad",
                "size": 1,
                "fields": [{"name": "x", "type": "u16be"}],
            }
        ).compile()


def test_yaml_catalog_loads_real_file(tmp_path) -> None:
    path = tmp_path / "codecs.yaml"
    path.write_text(
        """version: 1
codecs:
  state:
    fields:
      - name: mode
        type: enum
        values: {0x00: idle, 0x01: active}
""",
        encoding="utf-8",
    )
    catalog = catalog_from_yaml(path)
    assert catalog.decode("state", b"\x01") == {"mode": "active"}


def test_unknown_schema_key_is_rejected() -> None:
    with pytest.raises(SchemaError, match="unknown key"):
        layout_from_mapping({"fields": [{"name": "voltage", "type": "u16le", "scsale": 0.01}]})


def test_conflicting_aliases_are_rejected() -> None:
    with pytest.raises(SchemaError, match="disagree"):
        layout_from_mapping({"fields": [{"name": "value", "kind": "u8", "type": "u16be"}]})


def test_catalog_names_cannot_collide_after_normalization() -> None:
    with pytest.raises(SchemaError, match="Duplicate codec name"):
        catalog_from_mapping({"codecs": {"status": {"fields": []}, " status ": {"fields": []}}})


def test_enum_values_cannot_collide_after_normalization() -> None:
    with pytest.raises(SchemaError, match="Duplicate enum value"):
        layout_from_mapping(
            {"fields": [{"name": "mode", "type": "enum", "values": {1: "a", "0x1": "b"}}]}
        )


@pytest.mark.parametrize(
    "document",
    [
        "fields: []\nfields: []\n",
        "fields: [{name: x, type: u8, type: u16be}]\n",
        "fields: [{name: x, type: enum, values: {1: first, 1: second}}]\n",
        "codecs: {status: {fields: []}, status: {fields: []}}\n",
    ],
)
def test_yaml_duplicate_keys_raise_schema_error(tmp_path, document: str) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(document, encoding="utf-8")
    from structwire import layout_from_yaml

    with pytest.raises(SchemaError, match="Duplicate YAML key"):
        layout_from_yaml(path)


def test_malformed_yaml_raises_schema_error(tmp_path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("fields: [", encoding="utf-8")
    from structwire import layout_from_yaml

    with pytest.raises(SchemaError, match="Invalid YAML schema"):
        layout_from_yaml(path)


@pytest.mark.parametrize("loader", [layout_from_yaml, catalog_from_yaml])
@pytest.mark.parametrize(
    "scalar", ["!!int invalid", "!!float invalid", "!!bool invalid", "2026-99-99"]
)
def test_invalid_yaml_scalars_raise_schema_error(tmp_path, loader, scalar: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(f"fields: []\nsize: {scalar}\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="Invalid YAML schema"):
        loader(path)


@pytest.mark.parametrize("loader", [layout_from_yaml, catalog_from_yaml])
def test_invalid_yaml_encoding_raises_schema_error(tmp_path, loader) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_bytes(b"fields: []\n# \xff\n")
    with pytest.raises(SchemaError, match="Invalid YAML schema"):
        loader(path)


def test_yaml_object_constructor_is_rejected(tmp_path) -> None:
    path = tmp_path / "object.yaml"
    path.write_text("!!python/object/apply:os.system ['false']", encoding="utf-8")
    from structwire import layout_from_yaml

    with pytest.raises(SchemaError, match="Invalid YAML schema"):
        layout_from_yaml(path)


@pytest.mark.parametrize("attribute", ["scale", "bias"])
def test_mapping_boolean_scaling_is_rejected(attribute: str) -> None:
    with pytest.raises(SchemaError, match="boolean"):
        layout_from_mapping({"fields": [{"name": "x", "type": "u8", attribute: True}]})


def test_yaml_merge_duplicate_keys_are_rejected(tmp_path) -> None:
    path = tmp_path / "merge.yaml"
    path.write_text("<<: {fields: []}\nfields: []\n", encoding="utf-8")
    from structwire import layout_from_yaml

    with pytest.raises(SchemaError, match="Duplicate YAML key"):
        layout_from_yaml(path)


def test_quoted_yaml_boolean_labels_remain_strings(tmp_path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text('fields: [{name: mode, type: enum, values: {0: "off", 1: "on"}}]\n')
    from structwire import layout_from_yaml

    codec = layout_from_yaml(path).compile()
    assert codec.decode(b"\x01") == {"mode": "on"}
    assert codec.encode({"mode": "off"}) == b"\x00"


@pytest.mark.parametrize("attribute", ["offset", "length", "mask", "shift"])
@pytest.mark.parametrize("value", [True, 1.5])
def test_mapping_integer_parameters_do_not_truncate(attribute: str, value: object) -> None:
    with pytest.raises(SchemaError):
        layout_from_mapping({"fields": [{"name": "x", "type": "u8", attribute: value}]})


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("attribute", ["description", "unit"])
@pytest.mark.parametrize("value", [None, 1, []])
def test_field_metadata_types_are_consistent(source, attribute, value, tmp_path) -> None:
    data = {"fields": [{"name": "x", "kind": "u8", attribute: value}]}
    with pytest.raises(SchemaError, match=f"{attribute} must be a string"):
        if source == "constructor":
            Field(**data["fields"][0])
        elif source == "mapping":
            layout_from_mapping(data)
        else:
            path = tmp_path / "metadata.yaml"
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
            layout_from_yaml(path)


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("attribute", ["name", "description"])
@pytest.mark.parametrize("value", [None, 1, []])
def test_layout_metadata_types_are_consistent(source, attribute, value, tmp_path) -> None:
    data = {"fields": [], attribute: value}
    with pytest.raises(SchemaError, match=f"{attribute} must be a string"):
        if source == "constructor":
            Layout(**{attribute: value})
        elif source == "mapping":
            layout_from_mapping(data)
        else:
            path = tmp_path / "metadata.yaml"
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
            layout_from_yaml(path)


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("value", [None, False, 1, []])
def test_enum_label_types_are_consistent(source, value, tmp_path) -> None:
    field = {"name": "mode", "kind": "enum", "values": {1: value}}
    with pytest.raises(SchemaError, match="enum labels must be strings"):
        if source == "constructor":
            Field(**field)
        elif source == "mapping":
            layout_from_mapping({"fields": [field]})
        else:
            path = tmp_path / "enum.yaml"
            path.write_text(yaml.safe_dump({"fields": [field]}), encoding="utf-8")
            layout_from_yaml(path)


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("name", [None, False, 1])
def test_flag_name_types_are_consistent(source, name, tmp_path) -> None:
    field = {"name": "flags", "kind": "flags", "bits": {name: 1}}
    with pytest.raises(SchemaError, match="flag names must be non-empty strings"):
        if source == "constructor":
            Field(**field)
        elif source == "mapping":
            layout_from_mapping({"fields": [field]})
        else:
            path = tmp_path / "flags.yaml"
            path.write_text(yaml.safe_dump({"fields": [field]}), encoding="utf-8")
            layout_from_yaml(path)


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("name", [None, False, 1])
def test_catalog_name_types_are_consistent(source, name, tmp_path) -> None:
    with pytest.raises(SchemaError, match="codec names must be non-empty strings"):
        if source == "constructor":
            Catalog({name: Layout()})
        elif source == "mapping":
            catalog_from_mapping({"codecs": {name: {"fields": []}}})
        else:
            path = tmp_path / "catalog.yaml"
            path.write_text(yaml.safe_dump({"codecs": {name: {"fields": []}}}), encoding="utf-8")
            catalog_from_yaml(path)


@pytest.mark.parametrize(
    "data,default_name,expected",
    [
        ({"fields": []}, "", ""),
        ({"fields": []}, "status", "status"),
        ({"name": "status", "fields": []}, "", "status"),
        ({"name": "status", "fields": []}, "status", "status"),
    ],
)
def test_layout_default_name_behavior(data, default_name, expected) -> None:
    assert layout_from_mapping(data, default_name=default_name).name == expected


def test_nonempty_default_name_rejects_conflicting_explicit_name() -> None:
    with pytest.raises(SchemaError, match="conflicts"):
        layout_from_mapping({"name": "other", "fields": []}, default_name="status")


def test_valid_metadata_strings_are_preserved(tmp_path) -> None:
    field = {
        "name": "mode",
        "kind": "enum",
        "description": "État",
        "unit": "",
        "values": {0: "", 1: " active "},
    }
    data = {"name": "status", "description": " Status ", "fields": [field]}
    expected = Layout(Field(**field), name="status", description=" Status ").compile().describe()
    assert layout_from_mapping(data).compile().describe() == expected
    path = tmp_path / "metadata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert layout_from_yaml(path).compile().describe() == expected


FIELD_CASES = [
    (kind, {})
    for kind in (
        "u8",
        "i8",
        "u16be",
        "u16le",
        "i16be",
        "i16le",
        "u24be",
        "u24le",
        "i24be",
        "i24le",
        "u32be",
        "u32le",
        "i32be",
        "i32le",
        "u64be",
        "u64le",
        "i64be",
        "i64le",
        "f32be",
        "f32le",
        "f64be",
        "f64le",
        "bcd",
        "mac",
        "bool",
        "uint16_le",
        "mac_address",
    )
] + [
    ("ascii", {"length": 2}),
    ("bytes", {"length": 2}),
    ("raw", {"length": 2}),
    ("enum", {"values": {1: "active"}}),
    ("flags", {"bits": {"active": 1}}),
]


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize(
    "kind,options,attribute,allowed_kind",
    [
        (kind, options, attribute, allowed_kind)
        for kind, options in FIELD_CASES
        for attribute, allowed_kind in (("values", "enum"), ("bits", "flags"))
        if kind != allowed_kind
    ],
)
def test_unrelated_field_tables_are_rejected(
    source, kind, options, attribute, allowed_kind, tmp_path
) -> None:
    field = {"name": "value", "kind": kind, **options}
    field[attribute] = {1: "active"} if attribute == "values" else {"active": 1}
    with pytest.raises(SchemaError, match=f"{attribute} is only valid for {allowed_kind} fields"):
        if source == "constructor":
            Field(**field)
        elif source == "mapping":
            layout_from_mapping({"fields": [field]})
        else:
            path = tmp_path / "tables.yaml"
            path.write_text(yaml.safe_dump({"fields": [field]}), encoding="utf-8")
            layout_from_yaml(path)


@pytest.mark.parametrize("kind,options", FIELD_CASES)
def test_empty_unrelated_tables_allow_description_roundtrips(kind, options) -> None:
    field = {"name": "value", "kind": kind, "values": {}, "bits": {}, **options}
    codec = Layout(Field(**field)).compile()
    assert layout_from_mapping(codec.describe()).compile().describe() == codec.describe()


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("kind", ["ascii", "bytes", "raw"])
def test_missing_required_length_is_schema_error(source, kind, tmp_path) -> None:
    field = {"name": "value", "kind": kind}
    with pytest.raises(SchemaError, match="requires length"):
        if source == "constructor":
            Field(**field)
        elif source == "mapping":
            layout_from_mapping({"fields": [field]})
        else:
            path = tmp_path / "length.yaml"
            path.write_text(yaml.safe_dump({"fields": [field]}), encoding="utf-8")
            layout_from_yaml(path)


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize(
    "options,value,payload,effective",
    [
        ({"kind": "u16le", "byteorder": "big"}, 0x1234, b"\x34\x12", "little"),
        ({"kind": "uint16_be", "byteorder": "little"}, 0x1234, b"\x12\x34", "big"),
        ({"kind": "i8", "byteorder": "little"}, -1, b"\xff", "big"),
        ({"kind": "f32le", "byteorder": "big"}, 1.0, b"\x00\x00\x80\x3f", "little"),
        ({"kind": "f32be", "byteorder": "little"}, 1.0, b"\x3f\x80\x00\x00", "big"),
        ({"kind": "bcd", "length": 2, "byteorder": "little"}, 1234, b"\x12\x34", "little"),
        ({"kind": "ascii", "length": 2, "byteorder": "little"}, "ab", b"ab", "little"),
        ({"kind": "bytes", "length": 2, "byteorder": "little"}, b"ab", b"ab", "little"),
        (
            {"kind": "enum", "length": 2, "values": {0x1234: "active"}, "byteorder": "little"},
            "active",
            b"\x34\x12",
            "little",
        ),
        (
            {"kind": "flags", "length": 2, "bits": {"active": 0x100}, "byteorder": "little"},
            {"active": True},
            b"\x00\x01",
            "little",
        ),
        ({"kind": "bool", "length": 2, "byteorder": "little"}, True, b"\x01\x00", "little"),
    ],
)
def test_byteorder_policy_is_consistent(
    source, options, value, payload, effective, tmp_path
) -> None:
    field = {"name": "value", **options}
    if source == "constructor":
        codec = Layout(Field(**field)).compile()
    elif source == "mapping":
        codec = layout_from_mapping({"fields": [field]}).compile()
    else:
        path = tmp_path / "order.yaml"
        path.write_text(yaml.safe_dump({"fields": [field]}), encoding="utf-8")
        codec = layout_from_yaml(path).compile()
    assert codec.encode({"value": value}) == payload
    assert codec.decode(payload) == {"value": value}
    assert codec.fields[0].effective_byteorder == effective
    assert codec.describe()["fields"][0]["byteorder"] == effective
    restored = layout_from_mapping(codec.describe()).compile()
    assert restored.encode({"value": value}) == payload


@pytest.mark.parametrize("value", [None, False, 1, "status", [], [Layout()]])
def test_catalog_constructor_rejects_non_mappings(value) -> None:
    with pytest.raises(SchemaError, match="must be a mapping"):
        Catalog(value)


@pytest.mark.parametrize("source", ["constructor", "mapping", "yaml"])
@pytest.mark.parametrize("value", [None, False, 1, "invalid", []])
def test_invalid_catalog_entries_are_schema_errors(source, value, tmp_path) -> None:
    with pytest.raises(SchemaError, match="Layout or Codec|must be a mapping"):
        if source == "constructor":
            Catalog({"status": value})
        elif source == "mapping":
            catalog_from_mapping({"codecs": {"status": value}})
        else:
            path = tmp_path / "catalog.yaml"
            path.write_text(yaml.safe_dump({"codecs": {"status": value}}), encoding="utf-8")
            catalog_from_yaml(path)


def test_catalog_constructor_validates_entries_without_calling_arbitrary_compile() -> None:
    class Invalid:
        def compile(self):
            raise AssertionError("Must validate the entry type first")

    with pytest.raises(SchemaError, match="Layout or Codec"):
        Catalog({"invalid": Invalid()})


def test_catalog_mapping_contract() -> None:
    layout = Layout(Field("value", "u8"), name="status")
    compiled = layout.compile()
    inputs = {" status ": layout, "empty": Layout().compile()}
    catalog = Catalog(inputs)
    inputs.clear()
    assert catalog.names == ("status", "empty")
    assert tuple(catalog) == catalog.names
    assert len(catalog) == 2
    assert Catalog({"status": compiled})["status"] is compiled
    assert catalog.encode("status", {"value": 1}) == b"\x01"
    assert catalog.get("missing") is None
    with pytest.raises(KeyError, match="Unknown codec"):
        catalog["missing"]
    with pytest.raises(TypeError):
        catalog["new"] = compiled
    with pytest.raises(SchemaError, match="at least one codec"):
        Catalog({})
    with pytest.raises(SchemaError, match="Duplicate codec name"):
        Catalog({"status": layout, " status ": layout})
    with pytest.raises(SchemaError, match="conflicts"):
        Catalog({"other": compiled})
