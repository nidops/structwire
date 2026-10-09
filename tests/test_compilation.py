"""Compilation must depend on field count, not the declared payload extent."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import tracemalloc

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from structwire import Field, Layout, SchemaError


@pytest.mark.parametrize("kind", ["bytes", "ascii", "bcd"])
def test_large_spans_and_gaps_compile_with_bounded_allocations(kind: str) -> None:
    tracemalloc.start()
    try:
        codec = Layout(
            Field("wide", kind, length=1_000_000, offset=1_000_000),
            Field("tail", "u8"),
            size=3_000_000,
        ).compile()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert codec.size == 3_000_000
    assert codec.describe()["fields"][1]["offset"] == 2_000_000
    # A generous ceiling for a three-million-byte layout with two fields.
    assert peak < 512_000


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS guards the pathological regression")
def test_pathological_dimensions_in_memory_limited_process() -> None:
    program = textwrap.dedent("""
        import resource
        from structwire import DecodeError, Field, Layout, SchemaError

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        huge = 10**100
        assert Layout(size=huge).compile().size == huge
        for kind in ('bytes', 'ascii', 'bcd'):
            field = Field('wide', kind, length=huge, offset=huge)
            codec = Layout(field, Field('tail', 'u8')).compile()
            assert codec.size == 2 * huge + 1
            try:
                codec.decode(b'')
            except DecodeError:
                pass
            else:
                raise AssertionError('short payload accepted')
            for other in (Field('overlap', 'u8', offset=2 * huge - 1),):
                try:
                    Layout(field, other).compile()
                except SchemaError:
                    pass
                else:
                    raise AssertionError('overlap accepted')
        codec = Layout(Field('high', 'u8', offset=huge, mask=0xF0, shift=4),
                       Field('low', 'u8', offset=huge, mask=0x0F)).compile()
        assert codec.size == huge + 1
        invalid = [
            lambda: Field('enum', 'enum', length=huge, values={0: 'zero'}),
            lambda: Field('flags', 'flags', length=huge, bits={'bit': 1}),
            lambda: Field('bool', 'bool', length=huge),
            lambda: Field('shift', 'u8', mask=0xFF, shift=huge),
            lambda: Field('mask', 'bytes', length=huge, mask=1),
            lambda: Layout(Field('past_end', 'u8', offset=huge), size=1).compile(),
        ]
        for construct in invalid:
            try:
                construct()
            except SchemaError:
                pass
            else:
                raise AssertionError('invalid schema accepted')
    """)
    subprocess.run([sys.executable, "-I", "-c", program], check=True, timeout=15)


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_wide_span_and_masked_writer_rejected(reverse: bool) -> None:
    fields = [Field("wide", "bytes", length=1000), Field("bit", "u8", offset=999, mask=1)]
    if reverse:
        fields.reverse()
        # Keep both offsets explicit when reversing declaration order.
        fields[1] = Field("wide", "bytes", length=1000, offset=0)
    with pytest.raises(SchemaError, match="byte 999"):
        Layout(*fields).compile()


def test_zero_mask_bytes_do_not_claim_storage() -> None:
    codec = Layout(
        Field("masked", "u32be", offset=0, mask=0xFF00, shift=8),
        Field("prefix", "bytes", length=2, offset=0),
        Field("suffix", "u8", offset=3),
    ).compile()
    payload = b"abcd"
    assert codec.encode(codec.decode(payload)) == payload


@settings(max_examples=300, derandomize=True, deadline=None)
@given(
    definitions=st.lists(
        st.tuples(st.integers(0, 12), st.integers(1, 4), st.booleans(), st.integers(0, 31)),
        max_size=12,
    )
)
def test_sparse_overlap_check_matches_dense_reference(definitions) -> None:
    fields = []
    claimed = [0] * 16
    overlaps = False
    for index, (offset, width, little, shift) in enumerate(definitions):
        order = "little" if little else "big"
        # Either a full interval or a masked byte span, including zero mask bytes.
        mask = 1 << (shift % (width * 8)) if shift % 2 else None
        field = Field(
            str(index),
            "bool",
            length=width,
            offset=offset,
            byteorder=order,
            mask=mask,
            shift=(shift % (width * 8)) if mask else 0,
        )
        fields.append(field)
        masks = mask.to_bytes(width, order) if mask else b"\xff" * width
        for byte_index, byte_mask in enumerate(masks, offset):
            overlaps |= bool(claimed[byte_index] & byte_mask)
            claimed[byte_index] |= byte_mask
    if overlaps:
        with pytest.raises(SchemaError, match="overlap"):
            Layout(*fields).compile()
    else:
        codec = Layout(*fields).compile()
        assert codec.size == max((field.offset + field.width for field in fields), default=0)
