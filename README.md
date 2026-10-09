# StructWire

StructWire converts fixed-layout binary payloads to Python values and back.
Use it when a device message, file record or test fixture has a known byte layout.
Define fields in Python or YAML, then reuse a compiled codec to encode and decode.
Your application supplies the bytes and handles transport I/O and routing.

## Install

Python 3.11 or newer is required. Install from PyPI:

```bash
python -m pip install "structwire>=0.1.0.post1,<0.2"
```

Or install from the source checkout:

```bash
git clone https://github.com/nidops/structwire.git
cd structwire
python -m pip install .
```

Version `0.1.0.post1` is an alpha API. PyYAML is installed automatically for YAML loading.

## Quick start

```python
from structwire import Field, Layout

codec = Layout(
    Field("level", "i16le", scale=0.1),
    Field("quality", "u8"),
).compile()

payload = codec.encode({"level": 23.5, "quality": 1})
assert payload == bytes.fromhex("eb 00 01")
assert codec.decode(payload) == {"level": 23.5, "quality": 1}
```

Compile a layout once and reuse its codec.

## YAML example

Save this as `codecs.yaml`:

```yaml
version: 1
codecs:
  frame_status:
    size: 4
    fields:
      - name: phase
        type: enum
        values: {0: idle, 1: running, 2: paused}
      - name: value
        type: uint16_le
        offset: 2
        scale: 0.01
        unit: arbitrary
```

```python
from structwire import catalog_from_yaml

catalog = catalog_from_yaml("codecs.yaml")
payload = bytes.fromhex("01 00 64 00")
values = catalog.decode("frame_status", payload)
assert values == {"phase": "running", "value": 1.0}
assert catalog.encode("frame_status", values) == payload
```

Offsets and sizes are in bytes. Here, byte 1 is unused and encodes as zero.
`unit` is display metadata; it does not change the conversion.

## Supported layouts

- Signed and unsigned 8/16/24/32/64-bit integers, with explicit byte order.
- IEEE-754 32/64-bit floats, BCD, fixed ASCII, bytes and MAC addresses.
- Enums, named flags, booleans and masked sub-fields.
- Numeric scaling and bias, explicit offsets and optional total payload size.
- Immutable layouts and reusable compiled codecs, with exact-length decoding by default.
- Named catalogs and single-layout loaders for YAML or Python mappings.

## Limitations

Unscaled integers preserve their full range, including 64-bit values. Scaling uses
Python floats, so some values cannot be represented exactly. Integer encoding
rejects values between raw counts, allowing small rounding errors; decoding raises
`DecodeError` if scaling loses the original count. For exact arithmetic, decode
unscaled integers and convert them in your application.

Encoding zeroes unused bytes and bits, encodes booleans as 0 or 1, and writes only
declared masks from flags mappings. Arbitrary payloads may therefore change after
decoding and re-encoding. See the
[compatibility contract](https://github.com/nidops/structwire/blob/master/docs/COMPATIBILITY.md)
for precise round-trip and floating-point guarantees.

Variable-length fields, nested/repeated layouts and checksums are not supported.

Schemas are trusted configuration. Safe YAML loading does not impose resource
limits; applications must bound untrusted schema and payload sizes. See
[schema resource limits](https://github.com/nidops/structwire/blob/master/docs/SCHEMA.md#trusted-schemas-and-resource-limits).

## Documentation and examples

All examples use fictional values and are independent of specific products.

- [BCD records](https://github.com/nidops/structwire/blob/master/examples/bcd_record.py)
- [Packed bit fields](https://github.com/nidops/structwire/blob/master/examples/packed_fields.py)
- [YAML codec catalog](https://github.com/nidops/structwire/blob/master/examples/codecs.yaml)
- [BLE-style payload](https://github.com/nidops/structwire/blob/master/examples/ble_payload.py)
- [Generic message routing](https://github.com/nidops/structwire/blob/master/examples/transport_bindings.yaml)
- [Python API](https://github.com/nidops/structwire/blob/master/docs/API.md)
- [Schema reference](https://github.com/nidops/structwire/blob/master/docs/SCHEMA.md)
- [Examples](https://github.com/nidops/structwire/tree/master/examples)
- [Questions and bug reports](https://github.com/nidops/structwire/issues)

MIT. See [LICENSE](https://github.com/nidops/structwire/blob/master/LICENSE).
