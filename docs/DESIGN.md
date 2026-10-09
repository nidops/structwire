# Design

StructWire transforms between Python values and fixed-layout bytes. The calling
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
rejects ambiguous overlapping writers. `Codec` contains no per-call mutable state.

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

Integer encoding rejects off-grid values with a small floating-point arithmetic tolerance.
Scaled integer decoding verifies that inverse conversion recovers the original raw count;
loss of precision raises `DecodeError`. Unscaled integers retain their full declared range.
See [COMPATIBILITY.md](COMPATIBILITY.md) for the complete conversion contract.

## Unsupported layouts and operations

- variable-length fields and dependent lengths
- checksums/CRCs
- arbitrary cross-byte bit numbering conventions
- nested/repeated layouts
- protocol registries
- transport I/O
