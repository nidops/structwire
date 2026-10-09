# Encoding and compatibility contract

## API and versions

StructWire `0.1.0.post1` is an alpha API. Consumers that depend on this series can use
`structwire>=0.1.0.post1,<0.2`.

This post-release updates documentation, examples and test fixtures. The public
API, schema version and encoding/decoding behavior are unchanged from `0.1.0`.
The example files are teaching material, outside the library's compatibility
contract. Exact pins to `structwire==0.1.0` must be updated to select the post-release.

Schema documents have a separate `version: 1`. Unsupported schema versions,
unknown keys, conflicting aliases, and duplicate YAML mapping keys are rejected
with `SchemaError`. Duplicate keys introduced by YAML merges are also rejected;
an explicit mapping should define each key once. File access errors remain normal
`OSError` exceptions.

The CI matrix covers CPython 3.11–3.14 on Linux, Windows, and macOS. See
[contributing](../CONTRIBUTING.md) for the local and installed-distribution checks.

## Length and fields

`decode(payload)` requires the exact layout size. `strict=False` accepts and ignores
trailing bytes, while short payloads still fail. `encode(values)` requires every
field and rejects unknown fields. `require_all=False` leaves omitted fields zero.
Outputs always have the declared layout size.
Payloads must be `bytes`, `bytearray` or `memoryview`; integer lengths and
iterables are rejected with `DecodeError`. Mutable payloads are copied.

Offsets and sizes are integer byte counts. Masks and shifts are integer values;
booleans and fractional schema values are rejected. Overlapping fields must claim
disjoint bit masks. Field order determines implicit offsets, not ownership of bits.
Nonzero shifts require a mask. Integer/float `length` cannot override the width
declared by the kind.

## Numeric conversion

Unscaled integer fields return integers and encode integers without a floating-point
conversion, including the full signed and unsigned 64-bit ranges. Out-of-range
values raise `EncodeError`.

Scaled numeric fields use Python float arithmetic:

```text
physical = raw * scale + bias
raw = (physical - bias) / scale
```

Scale and bias must be finite, and scale must be nonzero. Integer encoding rejects
nonfinite and off-grid values. The inverse conversion allows absolute arithmetic
noise up to the larger of `1e-12` and one floating-point step at the computed raw
value. Cancellation from a bias can exceed that inverse tolerance; in this case,
the nearest integer must reproduce the input exactly through the forward conversion.
A distance of half a count or greater is always rejected. This tolerance is
for ordinary floating-point calculations, not an exact decimal arithmetic API.
Encoding also rejects integer inputs that lose precision when converted to float,
or inverse conversions whose forward result differs from the input by half a raw
count or more.

Scaled integer decoding verifies that inverse conversion recovers the original raw
integer. If scaling or bias erases a count or overflows, it raises `DecodeError`.
This applies to BCD as well as integer fields. Large 64-bit counters, very small
scales, or large biases can exceed float precision. Define an unscaled field and
apply `decimal.Decimal` or another exact conversion in the caller when needed.

Float fields use IEEE-754 binary32 or binary64; encoding rounds to that format.
NaN and infinity are supported float values. Scaling floating-point fields can
round values further. A finite value that becomes nonfinite during inverse
scaling raises `EncodeError`; a finite raw float that becomes nonfinite during
decoding raises `DecodeError`. NaN payload bits are not guaranteed to survive a
round trip.

## Canonical output and reserved data

StructWire constructs a new, initially zeroed payload. Unrepresented bytes and bits
are not preserved. Define reserved data as explicit `bytes` or integer fields if it
must be retained.

- Enums decode known values as labels and unknown values as raw integers; both can
  be encoded. Enum labels must be unique.
- Flags decode to a mapping of the declared names to booleans. A mapping encodes only
  named masks, clearing unnamed bits. Encode a raw integer to retain an externally
  stored bitset, or use an integer field to obtain the complete raw value. Composite
  masks use “any masked bit is set” when decoding and set the entire mask when
  encoding a true value, so those masks can also canonicalize bit patterns.
- Booleans decode any nonzero logical value as `True` and encode as 0 or 1.
- ASCII decoding removes trailing NUL padding; encoding adds NUL padding to the
  fixed width. Use `bytes` for uninterpreted content.
- MAC addresses decode to uppercase colon-separated strings. Encoding accepts six
  two-digit ASCII hex octets with consistent colons or hyphens (either letter case),
  or six bytes, with byte order applied as declared. Signs, whitespace, `0x`
  prefixes, mixed separators and short/long octets are rejected.

Byte-for-byte decode/encode identity requires a fully represented layout, canonical
flag/boolean values, and representable numeric conversions. A schema is a semantic
view of a payload, not a mechanism for retaining unmodeled bytes.
