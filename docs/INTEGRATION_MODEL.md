# Integration examples

These teaching examples use invented identifiers and payloads, not real-world
message definitions.

The application selects a codec and passes it payload bytes. It handles
identifiers, framing, checksums and device I/O. The YAML below is illustrative
**application configuration**; StructWire does not load the outer mappings.

## Named codec reference

A fictional message type can be mapped to a named catalog entry:

```yaml
messages:
  by_kind:
    status:
      codec: frame_status
```

The application looks up `frame_status` and calls
`catalog.decode("frame_status", payload)`.
See [catalog_demo.py](../examples/catalog_demo.py) and
[codecs.yaml](../examples/codecs.yaml) for runnable examples.

## Inline layout

Application configuration may also contain a complete synthetic layout:

```yaml
messages:
  by_kind:
    custom:
      layout:
        size: 2
        fields:
          - name: category
            type: enum
            values: {0: basic, 1: extended}
          - name: count
            type: uint8
```

The application extracts the nested `layout` mapping and passes it to
`layout_from_mapping(...).compile()`. All routing remains outside StructWire.

## Framed byte stream

For example, an imaginary stream might contain:

```text
C7 21 | <6 payload bytes> | checksum
```

The application checks the packet envelope, extracts six bytes and uses
`catalog.decode("environment_sample", payload)`. This library does **not**
implement the fictional envelope or checksum.

The [transport bindings](../examples/transport_bindings.yaml) and
[UART bindings](../examples/uart_bindings.yaml) illustrate application-owned
routing independently of any particular framework.
