# Encoding and compatibility contract

## API and versions

This document describes StructWire `1.0.0`. Private underscore names, repr
formatting, exact error text and example schemas are implementation details.

Schema version is `1`. Unknown keys, conflicting aliases, duplicate explicit
YAML keys and unsupported versions raise `SchemaError`. Inherited YAML merge keys
may be intentionally overridden by explicit keys. File errors raise `OSError`.

CPython 3.11–3.14 is the supported target on Linux, Windows and macOS. The CI files
define that matrix; a matrix definition alone is not proof of execution. A final
release requires results for all matrix entries. Local 3.11 results do not qualify
the other versions or platforms. No alternative interpreter guarantee is made.

## Length and fields

For fixed layouts, `decode(payload)` requires the exact layout size. `strict=False` accepts and ignores
trailing bytes, while short payloads still fail. `encode(values)` requires every
field and rejects unknown fields. `require_all=False` leaves omitted fields zero.
Fixed layouts encode exactly `size` bytes. A layout with a `rest` field is
variable: decoding requires at least `size` bytes and gives every trailing byte to
that field, and encoding appends the field's value after the fixed part.
Variable ASCII has no padding: its decoded string preserves trailing NULs, unlike
fixed-length ASCII, which removes trailing NUL padding.
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

Integer and BCD fields use exact arithmetic for integer or exactly integral float
inputs when both coefficients are integers, or when one coefficient is an integer
and the other is neutral (`scale=1.0` or `bias=0.0`). Exactly integral floats are
converted to integers before scaling. Other combinations use Python float arithmetic.
In particular, `scale=2` with the default bias is exact, while `scale=2.0` uses
floating-point arithmetic even though its value is integral. Float fields always
use floating-point conversion.

```text
physical = raw * scale + bias
raw = (physical - bias) / scale
```

Scale and bias must be finite, and scale must be nonzero. Integer encoding rejects booleans, nonfinite and off-grid values. Unscaled integer
and BCD inputs must be Python integers or exactly integral floats: even
`3.0000000000001` is rejected. Decimal, Fraction and numeric strings are not
implicitly converted. Floating fields accept int/float values but reject booleans.
Scaled inverse conversion alone uses the tolerance below. The inverse conversion allows absolute arithmetic
noise up to the larger of `1e-12` and one floating-point step at the computed raw
value. Cancellation from a bias can exceed that inverse tolerance; in this case,
the nearest integer must reproduce the input exactly through the forward conversion.
A distance of half a count or greater is always rejected. This tolerance is
for ordinary floating-point calculations, not an exact decimal arithmetic API.
Encoding also rejects integer inputs that lose precision when converted to float,
or inverse conversions whose forward result differs from the input by half a raw
count or more.

For exact-integer coefficients, an integer or exactly integral float physical input
must be exactly on the raw-count grid. A non-integral quotient is rejected without rounding. YAML
integer coefficients retain their integer type; coefficients declared as floats
keep the established precision checks unless they are neutral as described above.

```python
from structwire import Field, Layout, PrecisionError

wire = (2**64 - 1).to_bytes(8, "little")
exact = Layout(Field("count", "u64le", scale=2)).compile()
assert exact.decode(wire) == {"count": 2 * (2**64 - 1)}
assert exact.encode(exact.decode(wire)) == wire
floating = Layout(Field("count", "u64le", scale=2.0)).compile()
try:
    floating.decode(wire)
except PrecisionError:
    pass
else:
    raise AssertionError("Expected floating-point precision loss")
```

Scaled integer decoding verifies that inverse conversion recovers the original raw
integer. If scaling or bias erases a count, it raises `PrecisionError`, a subclass of
`DecodeError`. Numeric overflow remains a decoding error; malformed wire data is
never excused by selecting raw counts.
This applies to BCD as well as integer fields. Large 64-bit counters, very small
scales, or large biases can exceed float precision. Use `scaled=False` on encode/decode to bypass scale and bias for integers, BCD
and floats. Integers and BCD return exact raw counts; floats retain their wire
precision. Mask/sign extraction, enum labels, flag mappings, boolean conversion,
ASCII padding and canonical zero filling still apply. This is not a wire-image
preservation mode. Apply Decimal or Fraction in the caller using an explicitly
chosen precision/context and exact scale/bias constants when needed.

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
  stored bitset, or use an integer field to obtain the complete raw value. Disjoint composite
  masks use “any masked bit is set” when decoding and set the entire mask when
  encoding a true value, so those masks can canonicalize bit patterns. Overlapping
  masks within a flags field are rejected. Boolean raw values for enum/flags are
  rejected; boolean flag states remain supported.
- Booleans decode any nonzero logical value as `True` and encode as 0 or 1.
- Fixed-width ASCII decoding removes trailing NUL padding; encoding adds NUL padding
  to the fixed width. Variable ASCII preserves trailing NULs and adds no padding.
  Use `bytes` for uninterpreted content.
- MAC addresses decode to uppercase colon-separated strings. Encoding accepts six
  two-digit ASCII hex octets with consistent colons or hyphens (either letter case),
  or six bytes, with byte order applied as declared. Signs, whitespace, `0x`
  prefixes, mixed separators and short/long octets are rejected.

Byte-for-byte decode/encode identity requires a fully represented layout, canonical
flag/boolean values, and representable numeric conversions. A schema is a semantic
view of a payload, not a mechanism for retaining unmodeled bytes.
