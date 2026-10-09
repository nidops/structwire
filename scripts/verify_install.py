"""Run the packaged tests and examples from a clean, isolated installation."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import venv
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


def run(arguments: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    subprocess.run(arguments, cwd=cwd, env=environment, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("dist"))
    parser.add_argument("--distribution", choices=("wheel", "sdist"), default="wheel")
    parser.add_argument(
        "--index-url", help="Download and verify the exact wheel from a package index"
    )
    args = parser.parse_args()
    directory = args.directory.resolve()
    wheels, sdists = list(directory.glob("*.whl")), list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        parser.error("Expect exactly one wheel and one source distribution")
    if args.index_url and args.distribution != "wheel":
        parser.error("Index verification downloads the wheel")
    wheel, sdist = wheels[0], sdists[0]
    print(
        f"Checking {args.distribution} on Python {sys.version.split()[0]} ({sys.platform})",
        flush=True,
    )
    with ZipFile(wheel) as archive:
        (metadata_path,) = (
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        version = BytesParser().parsebytes(archive.read(metadata_path))["Version"]

    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    # Index, target, and extra-index settings from a caller must not redirect
    # the isolated installation or the explicit package-index verification.
    for key in list(environment):
        if key.startswith("PIP_"):
            environment.pop(key)
    environment["PIP_CONFIG_FILE"] = os.devnull
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="structwire-install-") as temporary:
        root = Path(temporary)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        pip = [str(python), "-I", "-m", "pip"]
        run([*pip, "install", "--upgrade", "pip"], cwd=root, environment=environment)
        with tarfile.open(sdist, "r:gz") as archive:
            archive.extractall(root / "source", filter="data")
        (source,) = (root / "source").iterdir()
        distribution = wheel if args.distribution == "wheel" else sdist
        if args.index_url:
            download = root / "download"
            download.mkdir()
            command = [
                *pip,
                "download",
                "--no-cache-dir",
                "--no-deps",
                "--only-binary=:all:",
                "--index-url",
                args.index_url,
                "--dest",
                str(download),
                f"structwire=={version}",
            ]
            for attempt in range(5):
                result = subprocess.run(command, cwd=root, env=environment)
                if result.returncode == 0:
                    break
                if attempt == 4:
                    result.check_returncode()
                time.sleep(5)
            (downloaded,) = download.glob("*.whl")
            if (
                hashlib.sha256(downloaded.read_bytes()).digest()
                != hashlib.sha256(wheel.read_bytes()).digest()
            ):
                raise ValueError("Index wheel differs from the verified release artifact")
            distribution = downloaded
        run(
            [*pip, "install", "--no-cache-dir", f"{distribution}[test]"],
            cwd=root,
            environment=environment,
        )
        run([*pip, "check"], cwd=root, environment=environment)
        smoke = (
            "import structwire, sys; from pathlib import Path; "
            "from importlib.metadata import version; "
            f"assert structwire.__version__ == version('structwire') == {version!r}; "
            "location = Path(structwire.__file__).resolve(); "
            "assert location.is_relative_to(Path(sys.prefix).resolve()); "
            "assert Path(structwire.__file__).with_name('py.typed').is_file(); "
            "codec = structwire.Layout(structwire.Field('value', 'u16le')).compile(); "
            "assert codec.decode(b'\\x34\\x12') == {'value': 0x1234}; "
            "assert codec.encode({'value': 0x1234}) == b'\\x34\\x12'; "
            "print('Installed:', structwire.__file__)"
        )
        run([str(python), "-I", "-c", smoke], cwd=root, environment=environment)
        run(
            [str(python), "-I", "-m", "pytest", "-o", "pythonpath=", "tests"],
            cwd=source,
            environment=environment,
        )


if __name__ == "__main__":
    main()
