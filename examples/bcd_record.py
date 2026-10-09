from structwire import Field, Layout

# Invented numeric record demonstrating one-byte and multi-byte packed BCD.
record = Layout(
    Field("batch", "bcd", length=2),
    Field("quantity", "bcd"),
    name="example-bcd-record",
).compile()

values = {"batch": 1234, "quantity": 25}
encoded = record.encode(values)

assert encoded == bytes.fromhex("12 34 25")
assert record.decode(encoded) == values
