"""Exercise the user-facing examples against the installed package."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from structwire import SchemaError, catalog_from_yaml, layout_from_mapping, layout_from_yaml
from structwire.loaders import _yaml_load

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PYTHON_BLOCKS = re.findall(r"```python\n(.*?)\n```", README, re.DOTALL)
YAML_BLOCKS = re.findall(r"```yaml\n(.*?)\n```", README, re.DOTALL)
DOC_PYTHON_BLOCKS = [
    pytest.param(code, id=f"{document.name}:{index}")
    for document in sorted((ROOT / "docs").glob("*.md"))
    for index, code in enumerate(
        re.findall(r"```python\n(.*?)\n```", document.read_text(encoding="utf-8"), re.DOTALL)
    )
]
DOC_YAML_BLOCKS = [
    pytest.param(code, id=f"{document.name}:{index}")
    for document in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    for index, code in enumerate(
        re.findall(r"```yaml\n(.*?)\n```", document.read_text(encoding="utf-8"), re.DOTALL)
    )
]


@pytest.mark.parametrize("example", sorted((ROOT / "examples").glob("*.py")), ids=lambda p: p.name)
def test_example_script_from_another_directory(example: Path, tmp_path: Path) -> None:
    subprocess.run([sys.executable, "-I", str(example)], cwd=tmp_path, check=True)


@pytest.mark.parametrize("code", PYTHON_BLOCKS, ids=lambda code: code.splitlines()[0])
def test_readme_python_example(code: str, tmp_path: Path) -> None:
    assert len(YAML_BLOCKS) == 1, "Update the README fixture when adding another YAML example"
    (tmp_path / "codecs.yaml").write_text(YAML_BLOCKS[0] + "\n", encoding="utf-8")
    subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, check=True)


@pytest.mark.parametrize("code", DOC_PYTHON_BLOCKS)
def test_documentation_python_example(code: str, tmp_path: Path) -> None:
    subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, check=True)


def validate_yaml_example(path: Path) -> None:
    data = _yaml_load(path)
    if "codecs" in data:
        catalog_from_yaml(path)
    elif "fields" in data:
        layout_from_yaml(path).compile()
    else:

        def validate_layouts(value: object) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key == "layout":
                        layout_from_mapping(nested).compile()
                    else:
                        validate_layouts(nested)
            elif isinstance(value, list):
                for nested in value:
                    validate_layouts(nested)

        validate_layouts(data)


@pytest.mark.parametrize("code", DOC_YAML_BLOCKS)
def test_documentation_yaml_example(code: str, tmp_path: Path) -> None:
    path = tmp_path / "example.yaml"
    path.write_text(code, encoding="utf-8")
    validate_yaml_example(path)


@pytest.mark.parametrize(
    "code",
    [
        "fields: []\nfields: []\n",
        "codecs: {status: {fields: []}, status: {fields: []}}\n",
        "routes: [{layout: {fields: [], fields: []}}]\n",
        "routes: [{layout: {fields: [{name: x, type: u8, type: u16be}]}}]\n",
    ],
)
def test_yaml_examples_reject_duplicate_keys(code: str, tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(code, encoding="utf-8")
    with pytest.raises(SchemaError, match="Duplicate YAML key"):
        validate_yaml_example(path)


def test_yaml_examples_validate_layouts_in_nested_lists(tmp_path: Path) -> None:
    path = tmp_path / "nested.yaml"
    path.write_text(
        "routes: [[{variants: [{layout: {fields: [{name: x, type: invalid}]}}]}]]\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="Unsupported field kind"):
        validate_yaml_example(path)


def test_example_bindings_reference_existing_codecs() -> None:
    catalog = catalog_from_yaml(ROOT / "examples" / "codecs.yaml")

    def validate_bindings(value: object) -> None:
        if isinstance(value, dict):
            if "codec" in value:
                assert value["codec"] in catalog
            if "layout" in value:
                layout_from_mapping(value["layout"]).compile()
            for nested in value.values():
                validate_bindings(nested)
        elif isinstance(value, list):
            for nested in value:
                validate_bindings(nested)

    for name in ("transport_bindings.yaml", "uart_bindings.yaml"):
        validate_bindings(_yaml_load(ROOT / "examples" / name))
