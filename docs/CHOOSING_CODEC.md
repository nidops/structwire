# Choosing a codec

| Tool | Useful fit | Tradeoff relative to StructWire |
| --- | --- | --- |
| Python `struct` | A small known sequence of primitive binary values | Compact and fast; application code supplies names, schema checks, masks and scaling. |
| StructWire | Named fields described in Python/YAML, explicit offsets and masks, physical scaling and one raw tail | Deliberately limited layouts; Python dictionaries and field semantics add overhead. |
| Construct | Declarative binary formats needing richer composition and parsing behavior | A broader parsing/building model; evaluate its constructs against the actual format. |
| bitstruct | Compact bit-oriented packing/unpacking | A bit-oriented format model; StructWire models byte spans with explicit masks instead. |

Choose `struct` when a format string and a few assignments are sufficient. Choose
StructWire when a shared, inspectable named schema reduces repeated conversion
code. For nested structures, dependent lengths or general bit streams, evaluate a
tool built for those requirements; StructWire does not implement them.

These are scope comparisons, not compatibility or performance claims about
particular third-party releases. Compare equivalent outputs: unpacking a tuple does less work
than validating a schema-derived record and constructing a dictionary.

For measurement, compile layouts before timing; warm up, repeat samples, and
report Python/platform, payloads, operation and time per call. Keep encoding and
decoding separate. A twenty-field loop does not establish application throughput.
