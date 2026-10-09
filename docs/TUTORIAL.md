# Decode a record and retain its raw count

Install StructWire 1.0.0. The application supplies a
complete payload; StructWire does not frame messages or communicate with devices.
This fictional record contains a scaled counter followed by opaque application data.

```python
from decimal import Decimal, localcontext
from structwire import Field, Layout, PrecisionError

record = Layout(
    Field("count", "u64le", scale=0.5),
    Field("data", "bytes", length="rest"),
    name="sample",
).compile()

wire = (2**64 - 1).to_bytes(8, "little") + b"AB\x00"
try:
    record.decode(wire)
except PrecisionError:
    pass  # A float cannot retain this count; the wire data itself is valid.
else:
    raise AssertionError("Expected precision loss")

raw = record.decode(wire, scaled=False)
assert raw == {"count": 2**64 - 1, "data": b"AB\x00"}
assert record.encode(raw, scaled=False) == wire

# Select exact constants and a context sufficient for this 64-bit calculation.
with localcontext() as context:
    context.prec = 40
    physical = Decimal(raw["count"]) * Decimal("0.5")
assert physical == Decimal("9223372036854775807.5")
print(f"Exact scaled count: {physical}")  # Exact scaled count: 9223372036854775807.5
```

For ordinary representable counts, the default physical-value path remains useful:

```python
from structwire import Field, Layout

record = Layout(Field("count", "u16le", scale=0.5), Field("data", "bytes", length="rest")).compile()
wire = record.encode({"count": 12.5, "data": b"payload"})
assert wire == b"\x19\x00payload"
assert record.decode(wire) == {"count": 12.5, "data": b"payload"}
```

Compile once when processing many payloads. Store application routing separately.
Use a named [catalog](API.md#catalogs-and-loaders) when several layouts are needed.
A raw-count decode still applies masking, enum/flag conversion and ASCII padding
rules; consult the [compatibility contract](COMPATIBILITY.md) before claiming a
byte-preserving round trip.
