from structwire import Field, Layout

# Invented record demonstrating two disjoint nibble masks in the same byte.
record = Layout(
    Field("upper_code", "u8", mask=0xF0, shift=4),
    Field("lower_code", "u8", offset=0, mask=0x0F),
    Field("reading", "u16le", scale=0.1),
    name="example-packed-fields",
).compile()

values = {"upper_code": 2, "lower_code": 7, "reading": 12.5}
payload = record.encode(values)
assert record.decode(payload) == values
print(payload.hex(" ").upper())
