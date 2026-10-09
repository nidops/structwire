# Python API

All names below are exported from `structwire`.
See the [schema reference](SCHEMA.md) for field kinds and options and the
[compatibility contract](COMPATIBILITY.md) for precision and canonical encoding.

## Fields and layouts

`Field(name, kind, ...)` describes one field. Optional arguments are `length`, `offset`, `mask`,
`shift`, `scale`, `bias`, `values`, `bits`, `byteorder`, `description` and `unit`.
Python constructors use these canonical names; the YAML key aliases `type`,
`bitmask`, `bitshift` and `physical_offset` belong to the loaders. Kind aliases
such as `uint16_le` work in both APIs.

`length="rest"` makes an ASCII or bytes field take all remaining bytes; see
[Trailing rest field](SCHEMA.md#trailing-rest-field). `Field.variable` reports
whether a field uses it; its `width` is then zero.

`Field.width` reports its storage size in bytes. `Field.effective_byteorder` reports the
byte order used by integer, float, enum, flag, boolean and MAC conversions.
BCD always stores its most significant decimal digits first; ASCII and bytes
retain their byte sequence. `Field.signed` identifies signed integer kinds.
Fields are immutable and copy their enum/flag tables into read-only mappings.
Field names, named layouts, catalog keys and flag names reject surrounding whitespace;
they are not silently trimmed. Layouts may be unnamed. Structural hashing of Field
and Layout is not a supported contract: their frozen mappings are unhashable.
Non-empty `values` is valid only for enums and non-empty `bits` only for flags;
empty mappings are accepted on other kinds so descriptions can be reloaded.
Numeric kinds take precedence over a conflicting `byteorder`; see the
[byte-order policy](SCHEMA.md#field-keys).

`Layout(*fields, name="", description="", size=None)` stores an ordered tuple of
fields. For fixed layouts, `size` can add reserved bytes but cannot truncate a field.
For a layout with a `rest` field, an explicit `size` must equal that field's offset.
An empty layout
is valid, with size zero unless a size is supplied. Layouts are immutable.

`layout.compile()` returns a `Codec`. Compilation resolves offsets and rejects
overlapping writers and undersized layouts with `SchemaError`. Reuse the compiled
codec when processing multiple payloads. `layout.encode(...)` and `layout.decode(...)`
are convenience methods that compile on each call and accept the same arguments
as the codec methods.

```python
from structwire import Field, Layout

codec = Layout(
    Field("counter", "u16le"),
    Field("state", "u8"),
    name="status",
    size=4,
).compile()
assert codec.size == 4
assert codec.fields[0].width == 2
assert codec.encode({"counter": 0x1234, "state": 1}) == b"\x34\x12\x01\x00"
```

## Compiled codecs

`Codec(layout)` is equivalent to `layout.compile()`. Its `layout`, `fields` and
`size` properties expose the source layout, ordered fields and exact payload size.
`variable` is true when the layout has a `rest` field; `size` is then the minimum
payload size and `strict` has no effect. Variable ASCII retains trailing NULs,
whereas fixed-width ASCII removes NUL padding.
Codecs keep no mutable state between calls and can be reused by independent callers.

| Method | Behavior |
|---|---|
| `decode(payload, *, strict=True, scaled=True)` | Accepts `bytes`, `bytearray` or `memoryview`; returns a new dictionary of named values. Fixed layouts require exact length by default; variable layouts require at least `size` bytes. |
| `decode(payload, strict=False)` | Fixed layouts ignore trailing bytes; variable layouts consume them in the `rest` field. Short payloads still raise `DecodeError`. |
| `encode(values, *, require_all=True, scaled=True)` | Accepts a mapping and returns new `bytes`. All fields are required by default; unknown names always raise `EncodeError`. |
| `encode(values, require_all=False)` | Leaves omitted fixed fields' storage bits zero, rather than applying a physical-value default. An omitted `rest` field adds no bytes. |
| `describe()` | Returns a new dictionary with layout metadata and resolved field offsets, widths, kinds, byte order and enum/flag tables. A `rest` field reports `length: "rest"`. |

`scaled=False` bypasses only scale/bias on integer, BCD and float fields, on both
encode and decode. All other validation and conversions still apply. Layout and
Catalog convenience methods forward the same keyword. Default `scaled=True`
preserves strict physical-value conversion; `PrecisionError` identifies loss of
integer precision. `repr(codec)` summarizes the name, field count, size and
variable flag; its exact formatting is not a serialization format.

Inputs are not modified. Encoding zeroes unrepresented bytes and bits. A zeroed
omitted field need not decode as physical zero: scaling, bias or enum labels can
give those bits a different meaning. Descriptions can be serialized with
`json.dumps` and loaded again with `layout_from_mapping`; modifying a description
does not change the codec.

## Catalogs and loaders

`Catalog(layouts)` accepts a non-empty mapping of names to `Layout` or `Codec`
objects and compiles layouts immediately. A layout's non-empty name must match its
catalog key. Catalogs implement the read-only `Mapping[str, Codec]` interface:
indexing, iteration, `len`, `keys`, `values`, `items` and `get` are available.
`catalog.names` returns names in declaration order. An unknown name raises `KeyError`.
Invalid containers or entries raise `SchemaError`.

`catalog.encode(name, values, *, require_all=True, scaled=True)` and
`catalog.decode(name, payload, *, strict=True, scaled=True)` delegate to that codec.
`catalog.describe()` returns a fresh mapping from names to codec descriptions.

```python
from structwire import Catalog, Field, Layout

catalog = Catalog({"status": Layout(Field("counter", "u8"))})
assert catalog.names == ("status",)
assert catalog.encode("status", {"counter": 7}) == b"\x07"
assert catalog.decode("status", b"\x07") == {"counter": 7}
```

| Loader | Input and result |
|---|---|
| `layout_from_mapping(data, *, default_name="")` | A single layout mapping; returns an uncompiled `Layout`. Uses `default_name` when `name` is omitted. A non-empty `default_name` must match an explicit layout name. |
| `layout_from_yaml(path)` | A UTF-8 YAML file containing a single layout; returns an uncompiled `Layout`. |
| `catalog_from_mapping(data)` | A versioned catalog mapping; returns a compiled `Catalog`. |
| `catalog_from_yaml(path)` | A UTF-8 YAML file containing a catalog; returns a compiled `Catalog`. |

File loaders accept a string or `pathlib.Path` path, not YAML text.
Loading a single layout validates its field definitions;
call `compile()` to also validate overlaps and total size. Catalog loading performs
both steps. See the [schema document shapes](SCHEMA.md).

## Formatting

`format_mac_address(data, *, byteorder="big")` accepts exactly six bytes as `bytes`,
`bytearray` or `memoryview` and returns uppercase colon-separated hexadecimal.
`byteorder="little"` reverses the address bytes. Invalid input raises `ValueError`.

`format_value(value)` converts byte buffers to uppercase, space-separated hex
(or `"<empty>"`), recursively visiting dictionaries, lists and tuples. Other values
are returned unchanged. `format_record(record)` applies it to each value in a
dictionary and returns a new dictionary. These helpers do not apply units or
change numeric values.

```python
from structwire import format_mac_address, format_record

assert format_mac_address(bytes.fromhex("01 23 45 67 89 AB")) == "01:23:45:67:89:AB"
assert format_record({"raw": b"\x01\xab", "count": 2}) == {"raw": "01 AB", "count": 2}
```

## Errors

`StructWireError` is the common base for `SchemaError`, `EncodeError` and
`DecodeError`. All three specific exceptions also inherit from `ValueError`.

- `SchemaError`: invalid field definitions, schema mappings or YAML, ambiguous
  overlaps, unsupported versions or an undersized layout.
- `EncodeError`: non-mapping input, unknown or missing fields, invalid values, values
  outside storage limits, off-grid scaled integers or finite values that overflow inverse scaling.
- `PrecisionError` (subclass of `DecodeError`): valid integer wire data loses counts during physical scaling; retry with `scaled=False`.
- `DecodeError`: invalid payload type or length (shorter than the minimum for a variable layout), malformed ASCII/BCD, scaled integer
  precision loss or finite float values that overflow scaling.

File access errors remain normal `OSError` exceptions.
BCD values that exceed Python's integer/string conversion limit raise `EncodeError`
or `DecodeError`.
The type annotations describe the supported public inputs; unrelated Python
programming errors are not uniformly converted to StructWire exceptions.
