"""Regression checks for the maintainer README CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_readme.py"
MARKDOWN = "# Guide café\n\n```python\nprint('example')\n```\n"


def test_readme_cli_defaults_to_working_directory(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(MARKDOWN, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--output", "preview.html"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "PyPI README renders" in result.stdout
    assert "Guide café" in (tmp_path / "preview.html").read_text(encoding="utf-8")


def test_readme_cli_accepts_custom_path_and_output(tmp_path: Path) -> None:
    readme = tmp_path / "guide.md"
    readme.write_text(MARKDOWN, encoding="utf-8")
    output = tmp_path / "preview" / "index.html"
    subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(readme), "--output", str(output)],
        cwd=tmp_path,
        check=True,
    )
    html = output.read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert "Guide café" in html
    assert "<pre" in html


@pytest.mark.parametrize(
    "link,error", [("relative.md", "relative link"), ("#missing", "missing anchor")]
)
def test_readme_cli_checks_selected_readme_links(link: str, error: str, tmp_path: Path) -> None:
    readme = tmp_path / "guide.md"
    readme.write_text(MARKDOWN + f"\n[Broken]({link})\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(readme)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert error in result.stderr


def test_readme_cli_preserves_repository_documentation_checks(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    (root / "scripts").mkdir(parents=True)
    (root / "docs").mkdir()
    script = root / "scripts" / "check_readme.py"
    shutil.copyfile(SCRIPT, script)
    (root / "pyproject.toml").write_text('[project]\nname = "structwire"\n', encoding="utf-8")
    (root / "README.md").write_text(MARKDOWN, encoding="utf-8")
    (root / "docs" / "REFERENCE.md").write_text("[Broken](missing.md)\n", encoding="utf-8")
    readme = tmp_path / "guide.md"
    readme.write_text(MARKDOWN, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(script), str(readme)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert f"{Path('docs') / 'REFERENCE.md'}: missing link missing.md" in result.stderr
