# YAML schema

Use a catalog when project configuration needs to reference codecs by name.

```yaml
version: 1
codecs:
  status:
    description: Example status payload
    size: 4
    fields:
      - name: mode
        type: enum
        values: {0: idle, 1: active}
      - name: voltage
        type: uint16_le
        offset: 2
        scale: 0.001
        unit: V
```

`version` defaults to `1`; other versions are rejected. `codecs` must be a non-empty
mapping. Load it with `catalog_from_yaml(path)` or `catalog_from_mapping(mapping)`.
Single-layout loaders accept a layout mapping directly, without `version` or
`codecs`. YAML loaders accept a file path, not YAML text. A single layout is
validated for overlaps and total size when compiled; catalog loading compiles
every layout immediately. See the [Python API](API.md).

## Layout keys

- `name`: optional; in a catalog it must match the catalog key
- `description`: human-readable metadata
- `size`: optional non-negative payload size in bytes, including gaps/trailing bytes;
  cannot truncate a field
- `fields`: required ordered list of field definitions; may be empty

Encoding fills unused bytes with zero; decoding does not preserve their values.

## Field keys

- `name`: unique field name
- `type` or `kind`: primitive encoding
- `offset`: optional byte offset
- `length`: positive byte count for ASCII/bytes/BCD or enum/flags/bool storage;
  for integer/float kinds it may only repeat the kind's fixed width
- `bitmask` / `mask`, `bitshift` / `shift`: shared-byte sub-fields
- `scale`, `bias`: numeric conversion using `value = raw * scale + bias`
- `values`: enum raw-value to label mapping; non-empty only for enums
- `bits`: named flag masks; non-empty only for flags
- `byteorder`: `big` (default) or `little` for enum/flags/bool storage and MAC addresses;
  integer/float byte order is determined by the kind; BCD/ASCII/bytes retain wire order
- `unit`: display/documentation metadata only
- `description`: display/documentation metadata only

Numeric `bias` also accepts the alias `physical_offset`. If both
spellings of an alias are supplied, their values must agree. Unknown catalog,
layout and field keys are rejected.

A valid `byteorder` is accepted on every kind. Integer/float
kind names take precedence even when the supplied order disagrees (including a
little-endian kind with the default `big`). BCD, ASCII and bytes ignore it and
retain wire order. `describe()` reports the kind-defined order for integers and
floats, and the supplied order for other kinds. Use `byteorder` only for
enum/flags/bool storage and MAC addresses in new schemas.

## Types and defaults

| Type | Width |
|---|---|
| `u8`, `i8`; `u16be`/`u16le` through `u64be`/`u64le` and signed equivalents | Declared by type; 24-bit integers are also supported |
| `f32be`, `f32le`, `f64be`, `f64le` | 4 or 8 bytes |
| `ascii`, `bytes` | Required `length` |
| `bcd` | `length`, default 1 byte |
| `mac` | 6 bytes |
| `enum`, `flags`, `bool` | `length`, default 1 byte; maximum 8 |

Omitted offsets place fields after the furthest occupied byte. `scale` defaults to
`1`, `bias` to `0`, and `shift` to `0`. Enums require `values`; flags require `bits`.
A nonzero shift requires a mask. After shifting, the mask must consist of
contiguous low bits, for example `mask: 0xF0` with `shift: 4`. Signed integer
sub-fields use the sign bit of that logical width, so an `i8` with `mask: 0x0F`
represents -8 through 7.
Masks apply only to integer, enum, flags and bool fields. They must be positive,
fit the field's storage width and have no set bits below the shift.

Integer schema values accept integers or strings with Python base prefixes,
such as `"0x10"`. Booleans and fractional values are rejected. Python constructors
require actual integers for these parameters. Names, descriptions, units and enum
labels must be strings; field, flag and catalog names must be non-empty. Enum
labels must be unique. Quote YAML labels such as
`"on"`, `"off"`, `"yes"` and `"no"`: PyYAML otherwise resolves these as booleans.

### Kind aliases

`uint8`/`int8` map to `u8`/`i8`. For widths 16, 24, 32 and 64,
`uint<width>_be`/`uint<width>_le` and `int<width>_be`/`int<width>_le` map to their
short names. `float32_be`, `float32_le`, `float64_be` and `float64_le` map to
`f32be`, `f32le`, `f64be` and `f64le`. `raw` means `bytes`; `mac_address` means
`mac`. Kinds ignore surrounding whitespace and letter case, and hyphens are
normalized to underscores.

### Decoded and encoded values

| Kind | Decoded value / accepted encoding input |
|---|---|
| Integer, BCD | Raw integer when unscaled; scaled numeric value otherwise. Encoding requires an integral raw count within range. |
| Float | Python float; encoding accepts numbers and rounds to the storage precision. |
| ASCII | String with trailing NUL padding removed; encoding accepts ASCII strings of at most `length` bytes and pads with NUL. |
| Bytes | `bytes`; encoding accepts bytes-convertible values of exactly `length`, except integer lengths. |
| MAC | Uppercase colon-separated string; encoding accepts six two-digit ASCII hexadecimal octets with a consistent colon or hyphen separator, or six bytes. `little` reverses wire storage. |
| Enum | Declared string label, or raw integer for unknown values; encoding accepts labels or raw integers. |
| Flags | Mapping of declared names to booleans; encoding accepts such a mapping with booleans/0/1, or a raw integer bitset. |
| Bool | `False` for zero, `True` for any nonzero logical value; encoding accepts booleans or integer 0/1. |

BCD stores two decimal digits per byte, most significant digits first, without
signs or decimal-point nibbles. Invalid nibbles raise `DecodeError`. `scale` and
`bias` are valid only for integer, float and BCD fields. Flags use any-set-bit
semantics for composite masks; mapping encoding can therefore canonicalize them.

Scale and bias must be finite, and scale must be nonzero. Integer encoding rejects
nonfinite and fractional raw values instead of truncating them. Inverse scaling
allows a small absolute floating-point tolerance. Half-count values are always
rejected. Scaled integer decoding verifies that inverse conversion recovers the
original raw count and raises `DecodeError` if precision is lost.

YAML mapping keys must be unique, including keys introduced by merges. Enum raw
keys must remain unique after conversion (for example, `1` and `"0x1"` conflict).
Malformed YAML raises `SchemaError`; files are loaded using safe YAML constructors.
See [COMPATIBILITY.md](COMPATIBILITY.md) for canonical encoding and precision limits.

## Shared bits

Masks apply to the numeric value of a field's byte span. Layout compilation rejects
overlapping fields unless their masks are disjoint:

```python
from structwire import Field, Layout

status = Layout(
    Field("upper_nibble", "u8", mask=0xF0, shift=4),
    Field("lower_nibble", "u8", offset=0, mask=0x0F),
).compile()

assert status.decode(b"\x53") == {"upper_nibble": 5, "lower_nibble": 3}
assert status.encode({"upper_nibble": 5, "lower_nibble": 3}) == b"\x53"
```

Routing keys belong in project configuration, outside this schema.

## Trusted schemas and resource limits

Schemas are trusted application configuration. Safe YAML constructors prevent
Python object construction; they do not make arbitrary YAML or schemas safe to
load from an untrusted source. Applications must bound schema file size, nesting,
field/table counts, widths, offsets and total layout size before loading or
compiling untrusted definitions.

Compilation uses O(F) auxiliary space and O(F log F) time for F fields, independent
of byte gaps and field widths: full-width writers use intervals and masked writers
claim at most eight bytes each. Integer storage for supplied offsets, widths and
table values still depends on their bit lengths. Field validation does not build
integers proportional to a declared byte width.

Large layouts can compile without being practical to encode or decode. Encoding
allocates the entire payload (including gaps) and returns a copy as `bytes`;
decoding copies mutable buffers and creates field values. Payload work and memory
therefore grow with the actual data size. BCD conversions also use Python's
integer/string conversion limits. StructWire imposes no application-specific
maximum layout size and does not turn resource exhaustion into `SchemaError`.
