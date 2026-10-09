"""The installed-artifact verifier must reject unsafe source archives on every Python."""

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "verify_install", Path(__file__).parents[1] / "scripts/verify_install.py"
)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def archive_of(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, kind in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.REGTYPE:
                info.size = 2
                archive.addfile(info, io.BytesIO(b"ok"))
            else:
                info.linkname = "../outside"
                archive.addfile(info)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../outside", tarfile.REGTYPE),
        ("/outside", tarfile.REGTYPE),
        ("root/../../outside", tarfile.REGTYPE),
        ("C:/outside", tarfile.REGTYPE),
        ("root\\outside", tarfile.REGTYPE),
        ("root/link", tarfile.SYMTYPE),
        ("root/link", tarfile.LNKTYPE),
        ("root/pipe", tarfile.FIFOTYPE),
    ],
)
def test_unsafe_archive_rejected_before_any_extraction(tmp_path, name, kind):
    with (
        archive_of([("root/good", tarfile.REGTYPE), (name, kind)]) as archive,
        pytest.raises(ValueError, match="Unsafe"),
    ):
        VERIFY.extract_source(archive, tmp_path / "target")
    assert not (tmp_path / "target").exists()


def test_regular_source_archive_is_portable(tmp_path):
    with archive_of([("root", tarfile.DIRTYPE), ("root/file", tarfile.REGTYPE)]) as archive:
        VERIFY.extract_source(archive, tmp_path / "target")
    assert (tmp_path / "target/root/file").read_bytes() == b"ok"


def test_extractor_never_overwrites_existing_directory(tmp_path):
    with archive_of([("file", tarfile.REGTYPE)]) as archive, pytest.raises(FileExistsError):
        VERIFY.extract_source(archive, tmp_path)


def test_duplicate_paths_are_rejected(tmp_path):
    with (
        archive_of([("root/file", tarfile.REGTYPE), ("root/./file", tarfile.REGTYPE)]) as archive,
        pytest.raises(ValueError, match="Duplicate"),
    ):
        VERIFY.extract_source(archive, tmp_path / "target")
