from pathlib import Path

from structwire import catalog_from_yaml

catalog = catalog_from_yaml(Path(__file__).with_name("codecs.yaml"))

# Purely synthetic example bytes: phase=running, both flags set, value=100.
payload = bytes.fromhex("01 03 10 27")
decoded = catalog.decode("frame_status", payload)
assert decoded == {"phase": "running", "ready": True, "flagged": True, "value": 100.0}
assert catalog.encode("frame_status", decoded) == payload

values = {
    "channel": 7,
    "state": "sampling",
    "temperature_c": 21.5,
    "humidity_pct": 48.0,
}
encoded = catalog.encode("environment_sample", values)
assert catalog.decode("environment_sample", encoded) == values
print(encoded.hex(" ").upper())
