"""Load layouts and catalogs from Python mappings or YAML files."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from .catalog import Catalog
from .errors import SchemaError
from .model import REST, Field, Layout

_LAYOUT_KEYS = {"name", "description", "size", "fields"}
_FIELD_KEYS = {
    "name",
    "kind",
    "type",
    "length",
    "offset",
    "mask",
    "bitmask",
    "shift",
    "bitshift",
    "scale",
    "bias",
    "physical_offset",
    "values",
    "bits",
    "byteorder",
    "description",
    "unit",
}
_CATALOG_KEYS = {"version", "codecs"}


def _intish(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer value here")
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def _expect_keys(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    if not isinstance(data, Mapping):
        raise SchemaError(f"{where} must be a mapping")
    unknown = sorted(str(key) for key in data if key not in allowed)
    if unknown:
        raise SchemaError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _length(value: Any) -> int | Literal["rest"]:
    if value == REST:
        return REST
    return _intish(value)


def _enum_values(data: Mapping[Any, Any]) -> dict[int, str]:
    values: dict[int, str] = {}
    for key, label in data.items():
        raw = _intish(key)
        if raw in values:
            raise SchemaError(f"Duplicate enum value after normalization: {raw}")
        values[raw] = label
    return values


def _floatish(value: Any) -> int | float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a scale or bias")
    # Preserve exact integer scaling coefficients from YAML/Python mappings.
    # Decimal strings still opt into ordinary floating-point conversion.
    return value if isinstance(value, int) else float(value)


def _alias_value(
    data: Mapping[str, Any],
    primary: str,
    alias: str,
    *,
    default: Any = None,
    where: str,
) -> Any:
    has_primary = primary in data
    has_alias = alias in data
    if has_primary and has_alias and data[primary] != data[alias]:
        raise SchemaError(f"{where}: {primary!r} and compatibility alias {alias!r} disagree")
    if has_primary:
        return data[primary]
    if has_alias:
        return data[alias]
    return default


def layout_from_mapping(data: Mapping[str, Any], *, default_name: str = "") -> Layout:
    """Build a :class:`Layout` from a plain mapping.

    Accepts the aliases ``type``, ``bitmask``, ``bitshift`` and ``physical_offset``.
    Unknown keys and conflicting aliases raise ``SchemaError``. Compile the
    returned layout to validate overlaps and total size.
    """
    _expect_keys(data, _LAYOUT_KEYS, "layout")
    raw_fields = data.get("fields")
    if not isinstance(raw_fields, list):
        raise SchemaError("Layout mapping must contain a 'fields' list")

    fields: list[Field] = []
    for index, raw in enumerate(raw_fields):
        where = f"fields[{index}]"
        if not isinstance(raw, Mapping):
            raise SchemaError(f"{where} must be a mapping")
        _expect_keys(raw, _FIELD_KEYS, where)

        name = raw.get("name")
        kind = _alias_value(raw, "kind", "type", where=where)
        if not isinstance(name, str) or not name.strip():
            raise SchemaError(f"{where}.name must be a non-empty string")
        if not isinstance(kind, str) or not kind.strip():
            raise SchemaError(f"{where}.kind/type must be a non-empty string")

        mask_raw = _alias_value(raw, "mask", "bitmask", where=where)
        shift_raw = _alias_value(raw, "shift", "bitshift", default=0, where=where)
        bias_raw = _alias_value(raw, "bias", "physical_offset", default=0.0, where=where)
        values_raw = raw.get("values", {})
        bits_raw = raw.get("bits", {})
        if not isinstance(values_raw, Mapping) or not isinstance(bits_raw, Mapping):
            raise SchemaError(f"{where}: values/bits must be mappings")

        try:
            field = Field(
                name=name,
                kind=kind,
                length=_length(raw["length"]) if raw.get("length") is not None else None,
                offset=_intish(raw["offset"]) if raw.get("offset") is not None else None,
                mask=_intish(mask_raw) if mask_raw is not None else None,
                shift=_intish(shift_raw),
                scale=_floatish(raw.get("scale", 1.0)),
                bias=_floatish(bias_raw),
                values=_enum_values(values_raw),
                bits={k: _intish(v) for k, v in bits_raw.items()},
                byteorder=raw.get("byteorder", "big"),
                description=raw.get("description", ""),
                unit=raw.get("unit", ""),
            )
        except SchemaError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise SchemaError(f"{where}: invalid field value: {exc}") from exc
        fields.append(field)

    name = data.get("name", default_name)
    if not isinstance(name, str):
        raise SchemaError("Layout name must be a string")
    if name != name.strip():
        raise SchemaError("Layout name must not contain surrounding whitespace")
    if default_name and name != default_name:
        raise SchemaError(f"Catalog key {default_name!r} conflicts with layout name {name!r}")
    size_raw = data.get("size")
    try:
        size = _intish(size_raw) if size_raw is not None else None
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"layout.size: invalid integer value {size_raw!r}") from exc
    return Layout(
        *fields,
        name=name,
        description=data.get("description", ""),
        size=size,
    )


def catalog_from_mapping(data: Mapping[str, Any]) -> Catalog:
    """Load and compile a catalog from a mapping.

    ``codecs`` maps names to layout definitions. ``version`` defaults to 1,
    the only supported schema version.
    """
    _expect_keys(data, _CATALOG_KEYS, "catalog")
    version = data.get("version", 1)
    try:
        parsed_version = _intish(version)
    except (TypeError, ValueError) as exc:
        raise SchemaError("Catalog version must be an integer") from exc
    if parsed_version != 1:
        raise SchemaError(f"Unsupported catalog version: {parsed_version}")

    raw_codecs = data.get("codecs")
    if not isinstance(raw_codecs, Mapping) or not raw_codecs:
        raise SchemaError("Catalog mapping must contain a non-empty 'codecs' mapping")

    layouts: dict[str, Layout] = {}
    for raw_name, raw_layout in raw_codecs.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise SchemaError("Catalog codec names must be non-empty strings")
        if raw_name != raw_name.strip():
            raise SchemaError("Catalog codec names must not contain surrounding whitespace")
        name = raw_name
        if name in layouts:
            raise SchemaError(f"Duplicate codec name: {name!r}")
        if not isinstance(raw_layout, Mapping):
            raise SchemaError(f"codecs.{name} must be a mapping")
        layouts[name] = layout_from_mapping(raw_layout, default_name=name)
    return Catalog(layouts)


def _yaml_load(path: str | Path) -> Mapping[str, Any]:
    import yaml

    class UniqueSafeLoader(yaml.SafeLoader):
        # A new loader class is created for every file; aliases may reuse nodes.
        checked: set[int] = set()

        def flatten_mapping(self, node: yaml.MappingNode) -> None:
            if id(node) in self.checked:
                return
            self.checked.add(id(node))
            seen: set[Any] = set()
            for key_node, _ in node.value:
                key = (
                    "<<"
                    if key_node.tag == "tag:yaml.org,2002:merge"
                    else self.construct_object(key_node)
                )
                try:
                    if key in seen:
                        raise SchemaError(
                            f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}"
                        )
                    seen.add(key)
                except TypeError as exc:
                    raise SchemaError("YAML mapping keys must be hashable") from exc
            super().flatten_mapping(node)

        def construct_yaml_int(self, node: yaml.ScalarNode) -> int:
            value = node.value.replace("_", "").lstrip("+-")
            if (len(value) > 1 and value.startswith("0") and value.isdecimal()) or ":" in value:
                raise SchemaError(
                    f"ambiguous YAML integer {node.value!r} at line {node.start_mark.line + 1}; "
                    "use decimal digits without leading zeros or a quoted 0o/0x/0b value"
                )
            return super().construct_yaml_int(node)

    UniqueSafeLoader.add_constructor("tag:yaml.org,2002:int", UniqueSafeLoader.construct_yaml_int)

    with Path(path).open("r", encoding="utf-8") as handle:
        try:
            data = yaml.load(handle, Loader=UniqueSafeLoader)
        except SchemaError:
            raise
        except (yaml.YAMLError, ValueError, KeyError) as exc:
            raise SchemaError(f"Invalid YAML schema: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SchemaError("YAML root must be a mapping")
    return data


def layout_from_yaml(path: str | Path) -> Layout:
    """Load one layout from YAML."""
    return layout_from_mapping(_yaml_load(path))


def catalog_from_yaml(path: str | Path) -> Catalog:
    """Load a named codec catalog from YAML."""
    return catalog_from_mapping(_yaml_load(path))
