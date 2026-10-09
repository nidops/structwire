# Common errors

| Symptom | Meaning and action |
| --- | --- |
| `PrecisionError` decoding a large scaled integer | Floating-point scaling can lose the raw count, including with an integral-valued float such as `2.0`. Decode with `scaled=False`; perform exact arithmetic in the caller if needed. |
| `EncodeError` for a nearly integral number | Unscaled integer inputs must be exactly integral. Fix the producing calculation; the codec does not silently round fractional counts. |
| Boolean rejected as a count | Use integer `0`/`1` for numeric and enum/flags raw values. Bool fields and individual flag states accept booleans. |
| YAML enum label is not a string | Quote labels such as `"on"`, `"off"`, `"yes"`, `"no"` and numeric-looking labels. |
| Ambiguous YAML integer | Replace `010` with decimal `10` or quoted `"0o10"` according to intent. Sexagesimal integers are not accepted. |
| Duplicate YAML key | Remove the duplicate explicit key. Use one `<<` merge or merge sequence and an explicit override when inheritance is intended. |
| Overlapping flag masks | Give each named flag disjoint storage bits. Composite masks are allowed if disjoint; use an integer field to represent arbitrary overlapping views in application code. |
| Whitespace in an identifier | Correct the spelling rather than relying on silent trimming. Display descriptions and enum labels can retain whitespace. |
| Hashing Field/Layout raises `TypeError` | Frozen does not mean structurally hashable. Use your own stable schema identifier as a dictionary key. |
| `rest` field schema fails | Only ASCII/bytes support it; every other field must end at or before its offset, and explicit size must equal that offset. |
| Decode/encode changes the bytes | Check unrepresented gaps/bits, flag/boolean canonicalization, fixed ASCII padding and float NaN representations. Raw-count mode does not preserve all wire details. |

Safe YAML construction is not a resource limit. Bound schema and payload sizes
before accepting untrusted input. See [schema limits](SCHEMA.md#trusted-schemas-and-resource-limits).
