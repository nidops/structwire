"""Full-width integer scaling must never pass through lossy float arithmetic."""

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from structwire import EncodeError, Field, Layout, layout_from_mapping, layout_from_yaml


@pytest.mark.parametrize(
    "kind,count",
    [
        ("u64le", 2**53 + 1),
        ("u64le", 2**64 - 1),
        ("i64be", -(2**63)),
        ("i64be", 2**63 - 1),
    ],
)
@pytest.mark.parametrize("scale,bias", [(2, 0), (-3, 5), (2, 0.0)])
def test_exact_integer_affine_boundaries(kind, count, scale, bias):
    codec = Layout(Field("count", kind, scale=scale, bias=bias)).compile()
    physical = count * int(scale) + int(bias)
    wire = codec.encode({"count": count}, scaled=False)
    assert codec.decode(wire) == {"count": physical}
    assert codec.encode({"count": physical}) == wire


def test_integer_affine_off_grid_rejected():
    codec = Layout(Field("count", "u64le", scale=2, bias=1)).compile()
    with pytest.raises(EncodeError, match="not exactly representable"):
        codec.encode({"count": 2**54})


@pytest.mark.parametrize(
    "field,physical,wire",
    [
        (Field("count", "u64le", bias=1), 2**53 + 4, (2**53 + 3).to_bytes(8, "little")),
        (Field("count", "i8", bias=2**53 + 1), 2**53, b"\xff"),
        (Field("count", "i8", bias=2**53 + 1), 2**53 + 2, b"\x01"),
        (Field("count", "i8", bias=-(2**53 + 1)), -(2**53), b"\x01"),
        (Field("count", "i8", scale=-1, bias=2**53 + 1), 2**53, b"\x01"),
        (Field("count", "u8", scale=2**53 + 1, bias=-1), 2**53, b"\x01"),
        (
            Field("count", "bcd", length=8, bias=1),
            2**53 + 4,
            bytes.fromhex("90 07 19 92 54 74 09 95"),
        ),
    ],
)
def test_integral_float_and_integer_encode_the_same_exact_count(field, physical, wire):
    codec = Layout(field).compile()
    assert float(physical) == physical
    assert codec.encode({"count": physical}) == wire
    assert codec.encode({"count": float(physical)}) == wire
    assert codec.decode(wire) == {"count": physical}


@pytest.mark.parametrize("scale,bias", [(2, 1), (2, 2**53 + 1), (2**53 + 1, 0.0)])
def test_integral_float_off_grid_is_rejected_with_exact_coefficients(scale, bias):
    codec = Layout(Field("count", "u64le", scale=scale, bias=bias)).compile()
    for physical in (2**53, float(2**53)):
        with pytest.raises(EncodeError, match="not exactly representable"):
            codec.encode({"count": physical})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_exact_coefficients_reject_nonfinite_float_inputs(value):
    codec = Layout(Field("count", "u8", scale=2)).compile()
    with pytest.raises(EncodeError, match="finite"):
        codec.encode({"count": value})


def test_exact_coefficients_keep_fractional_float_arithmetic_tolerance():
    codec = Layout(Field("count", "u8", scale=2)).compile()
    assert codec.encode({"count": 6.0000000000001}) == b"\x03"
    with pytest.raises(EncodeError, match="not exactly representable"):
        codec.encode({"count": 6.25})


def test_integer_coefficients_survive_mapping_loader():
    layout = layout_from_mapping(
        {
            "fields": [{"name": "count", "kind": "u64le", "scale": 2, "bias": 0}],
        }
    )
    codec = layout.compile()
    raw = 2**53 + 1
    wire = raw.to_bytes(8, "little")
    assert codec.decode(wire) == {"count": raw * 2}
    assert codec.encode({"count": raw * 2}) == wire


def test_explicit_float_coefficients_keep_existing_precision_protection():
    from structwire import PrecisionError

    codec = Layout(Field("count", "u64le", scale=2.0, bias=0.0)).compile()
    with pytest.raises(PrecisionError):
        codec.decode((2**53 + 1).to_bytes(8, "little"))


@pytest.mark.parametrize("source", ["python", "mapping", "yaml"])
@pytest.mark.parametrize(
    "coefficients",
    [{"scale": 2}, {"bias": 2**53 + 1}, {"scale": -3, "bias": 2**53 + 1}],
)
def test_integer_coefficients_and_neutral_defaults(source, coefficients, tmp_path):
    definition = {"name": "count", "kind": "u64le", **coefficients}
    if source == "python":
        layout = Layout(Field(**definition))
    elif source == "mapping":
        layout = layout_from_mapping({"fields": [definition]})
    else:
        path = tmp_path / "exact.yaml"
        path.write_text(yaml.safe_dump({"fields": [definition]}), encoding="utf-8")
        layout = layout_from_yaml(path)
    field = layout.fields[0]
    for name, value in coefficients.items():
        assert type(getattr(field, name)) is int
        assert getattr(field, name) == value
    raw = 2**64 - 1
    physical = raw * coefficients.get("scale", 1) + coefficients.get("bias", 0)
    wire = b"\xff" * 8
    assert layout.decode(wire) == {"count": physical}
    assert type(layout.decode(wire)["count"]) is int
    assert layout.encode({"count": physical}) == wire


@pytest.mark.parametrize("scale", ["2.0", '"2"'])
def test_yaml_float_and_string_coefficients_keep_float_precision_checks(scale, tmp_path):
    from structwire import PrecisionError

    path = tmp_path / "floating.yaml"
    path.write_text(f"fields: [{{name: count, kind: u64le, scale: {scale}}}]", encoding="utf-8")
    codec = layout_from_yaml(path).compile()
    assert type(codec.fields[0].scale) is float
    with pytest.raises(PrecisionError):
        codec.decode((2**53 + 1).to_bytes(8, "little"))


@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("order", ["little", "big"])
@settings(max_examples=150, derandomize=True, deadline=None)
@given(
    raw=st.integers(0, 2**64 - 1),
    scale=st.sampled_from([-3, -1, 1, 2, 2**53 + 1]),
    bias=st.integers(-(2**64), 2**64),
)
def test_exact_affine_full_width_property(signed, order, raw, scale, bias):
    count = raw - 2**63 if signed else raw
    kind = ("i" if signed else "u") + "64" + ("le" if order == "little" else "be")
    codec = Layout(Field("count", kind, scale=scale, bias=bias)).compile()
    wire = count.to_bytes(8, order, signed=signed)
    physical = count * scale + bias
    assert codec.decode(wire) == {"count": physical}
    assert codec.encode({"count": physical}) == wire
    assert codec.decode(wire, scaled=False) == {"count": count}
    if abs(scale) > 1:
        with pytest.raises(EncodeError, match="not exactly representable"):
            codec.encode({"count": physical + 1})


@pytest.mark.parametrize(
    "field,wire,raw",
    [
        (Field("count", "bcd", length=10, scale=2), b"\x99" * 10, 10**20 - 1),
        (Field("count", "i64be", mask=2**64 - 2, shift=1, scale=-3), b"\x80" + b"\0" * 7, -(2**62)),
    ],
)
def test_exact_scaling_preserves_bcd_and_signed_mask_semantics(field, wire, raw):
    codec = Layout(field).compile()
    physical = raw * field.scale
    assert codec.decode(wire) == {"count": physical}
    assert codec.encode({"count": physical}) == wire
