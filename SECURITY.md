# Security policy

StructWire parses binary payloads using caller-supplied schemas. Report vulnerabilities
privately through the repository's security-advisory feature rather than a public issue.
Only the latest released `0.x` version receives fixes.

Schemas are trusted application configuration. YAML loading uses safe constructors
and rejects duplicate mapping keys, without arbitrary Python object construction;
it does not limit input size, nesting or resource consumption. Applications own
access control and resource limits for schemas and payloads. Bound widths, offsets,
layout sizes and field/table counts before accepting untrusted schemas. Encoding
still allocates a complete payload even when a sparse layout compiles cheaply.
See [schema resource limits](docs/SCHEMA.md#trusted-schemas-and-resource-limits).
