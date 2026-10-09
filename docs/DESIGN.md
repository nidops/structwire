# Design

StructWire transforms between Python values and schema-defined binary payloads. The calling
application handles protocol routing and device I/O; loaders read schema files.

## Core model

```text
Field definitions
       |
       v
     Layout
       |
       | compile()
       v
     Codec
       +-- encode(values) --> bytes
       +-- decode(bytes)  --> values
```

`Layout` and `Field` are immutable. Compilation resolves byte offsets, computes total size and
rejects ambiguous overlapping writers. Integer metadata, byte order, fixed ends,
masked write bytes and float `struct.Struct` objects are cached in frozen compiled
records. Unmasked writes use byte slices; shared-byte masks use explicit merges.
`Codec` contains no per-call mutable state. No batching or runtime code generation
is needed for these optimizations.

## Offset model

`Field.offset` is a byte offset. If omitted, a field starts after the furthest byte occupied so far.
Explicit offsets allow gaps and intentional shared bytes. Shared-byte encoding is accepted only
when masks are disjoint, which avoids order-dependent writes.

## Physical values

For numeric fields:

```text
physical = raw * scale + bias
raw      = (physical - bias) / scale
```

Unscaled integer encoding requires exact integrality. Integer/BCD scaling with
integer values and integer coefficients (or a neutral default coefficient) uses
exact arithmetic and rejects off-grid values. Floating-point inverse conversion
uses a small tolerance for arithmetic noise.
Scaled integer decoding verifies that inverse conversion recovers the original raw count;
loss of precision raises `PrecisionError` (a `DecodeError`). `scaled=False` bypasses
scale/bias while keeping every other field rule. Unscaled integers retain their full
declared range. No implicit Decimal/Fraction return type is introduced.
See [COMPATIBILITY.md](COMPATIBILITY.md) for the complete conversion contract.

## Unsupported layouts and operations

- variable-length fields other than one trailing `rest` field, and dependent lengths
- checksums/CRCs
- arbitrary cross-byte bit numbering conventions
- nested/repeated layouts
- protocol registries
- transport I/O
