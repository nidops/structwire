"""Validate release metadata, contents, and agreement between wheel and sdist."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def inspect_distributions(directory: Path, tag: str | None = None) -> dict:
    wheels = list(directory.glob("*.whl"))
    sdists = list(directory.glob("*.tar.gz"))
    require(len(wheels) == len(sdists) == 1, "Expect exactly one wheel and one source distribution")
    wheel, sdist = wheels[0], sdists[0]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel archive paths")
        wheel_files = {name: archive.read(name) for name in names if not name.endswith("/")}
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        require(all(item.isfile() or item.isdir() for item in members), "Unexpected sdist link")
        roots = {PurePosixPath(item.name).parts[0] for item in members}
        require(len(roots) == 1, "Source distribution must have one root directory")
        sdist_files = {}
        for item in members:
            path = PurePosixPath(item.name)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe archive path")
            if item.isfile():
                relative = path.relative_to(next(iter(roots))).as_posix()
                require(relative not in sdist_files, "Duplicate sdist archive path")
                handle = archive.extractfile(item)
                require(handle is not None, "Missing sdist file contents")
                sdist_files[relative] = handle.read()

    metadata_paths = [name for name in wheel_files if name.endswith(".dist-info/METADATA")]
    require(len(metadata_paths) == 1, "Missing or ambiguous wheel metadata")
    metadata = BytesParser().parsebytes(wheel_files[metadata_paths[0]])
    source_metadata = BytesParser().parsebytes(sdist_files["PKG-INFO"])
    version = metadata["Version"]
    for key in ("Name", "Version", "Requires-Python", "License-Expression"):
        require(metadata[key] == source_metadata[key], f"Wheel/sdist metadata mismatch: {key}")
    require(metadata["Name"] == "structwire", "Incorrect project name")
    require(metadata["Requires-Python"] == ">=3.11", "Incorrect Python requirement")
    require(metadata["License-Expression"] == "MIT", "Missing SPDX license expression")
    require("LICENSE" in metadata.get_all("License-File", []), "Missing license metadata")
    require(metadata["Author"] == "Nidhal Abidi", "Incorrect author metadata")
    require(
        metadata["Description-Content-Type"] == "text/markdown", "Incorrect README content type"
    )
    require(
        metadata.get_payload().strip() == sdist_files["README.md"].decode().strip(),
        "README mismatch",
    )
    require(
        wheel.name == f"structwire-{version}-py3-none-any.whl", "Incorrect pure-Python wheel name"
    )
    require(sdist.name == f"structwire-{version}.tar.gz", "Incorrect source distribution name")
    if tag is not None:
        require(tag == f"v{version}", f"Release tag {tag!r} does not match version {version!r}")

    assignments = ast.parse(sdist_files["src/structwire/__init__.py"])
    package_version = next(
        ast.literal_eval(node.value)
        for node in assignments.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    )
    require(package_version == version, "Package and distribution versions differ")
    require(
        set(metadata.get_all("Provides-Extra", [])) == {"test", "dev"}, "Missing development extras"
    )
    urls = metadata.get_all("Project-URL", [])
    for label in ("Homepage", "Documentation", "Source", "Issues"):
        require(
            any(url.startswith(f"{label}, https://github.com/nidops/structwire") for url in urls),
            f"Missing project URL: {label}",
        )

    info = metadata_paths[0].split("/")[0]
    require(
        all(name.startswith(("structwire/", f"{info}/")) for name in wheel_files),
        "Wheel contains files outside the package and metadata",
    )
    require("structwire/py.typed" in wheel_files, "Missing PEP 561 marker")
    require(wheel_files[f"{info}/licenses/LICENSE"] == sdist_files["LICENSE"], "License mismatch")
    package_files = {
        name: data for name, data in wheel_files.items() if name.startswith("structwire/")
    }
    source_files = {
        name.removeprefix("src/"): data
        for name, data in sdist_files.items()
        if name.startswith("src/structwire/")
    }
    require(package_files == source_files, "Wheel package does not match the source distribution")
    for prefix in ("docs/", "examples/", "tests/", "scripts/"):
        require(
            any(name.startswith(prefix) for name in sdist_files), f"Missing source files: {prefix}"
        )
    for name in (*wheel_files, *sdist_files):
        path = PurePosixPath(name)
        require(
            not set(path.parts) & {"artifacts", "__pycache__", ".git", ".github", ".venv"},
            f"Unexpected private/generated path: {name}",
        )
        require(
            not name.endswith((".pyc", ".pyo", ".local.yaml", ".local.yml")),
            f"Unexpected private/generated file: {name}",
        )
        require(not path.name.startswith(".env"), f"Environment file in distribution: {name}")
    return {
        "name": "structwire",
        "version": version,
        "package_files": len(package_files),
        "wheel_files": len(wheel_files),
        "sdist_files": len(sdist_files),
        "artifacts": [
            {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (wheel, sdist)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("dist"))
    parser.add_argument(
        "--tag", help="Require a version tag matching the built version (e.g. v0.1.0.post1)"
    )
    args = parser.parse_args()
    print(json.dumps(inspect_distributions(args.directory, args.tag), indent=2))


if __name__ == "__main__":
    main()
