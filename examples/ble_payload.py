from structwire import Field, Layout

# Invented BLE application payload. Not based on any product's GATT specification.
measurement = Layout(
    Field("format", "u8"),
    Field("channel", "u8"),
    Field("temperature_c", "i16le", scale=0.1),
    Field("humidity_pct", "u8"),
    Field("battery_pct", "u8"),
    name="example-ble-measurement",
).compile()

values = {
    "format": 1,
    "channel": 3,
    "temperature_c": 21.5,
    "humidity_pct": 48,
    "battery_pct": 82,
}
raw = measurement.encode(values)
assert measurement.decode(raw) == values
