"""Render the PyPI README and validate local documentation paths and anchors."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from readme_renderer.markdown import render


def prose(markdown: str) -> str:
    return re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", markdown, flags=re.M | re.S)


def anchors(path: Path) -> set[str]:
    result: set[str] = set()
    counts: dict[str, int] = {}
    markdown = path.read_text(encoding="utf-8")
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", prose(markdown), re.M):
        heading = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    result.update(re.findall(r'<(?:a|\w+)\b[^>]*\bid=["\']([^"\']+)', markdown))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("readme", type=Path, nargs="?", default=Path("README.md"))
    parser.add_argument("--output", type=Path, help="Write a local HTML preview")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "name"
    ]
    readme = args.readme.resolve()
    markdown = readme.read_text(encoding="utf-8")
    html = render(markdown)
    if not html or not re.search(r"<h1(?:\s|>)", html) or not re.search(r"<pre(?:\s|>)", html):
        raise ValueError("README failed to render a complete PyPI description")
    checked = 0
    documents = sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))
    if readme not in documents:
        documents.append(readme)
    for document in documents:
        label = document.relative_to(root) if document.is_relative_to(root) else document
        for target in re.findall(
            r"\[[^\]]*\]\(([^)]+)\)", prose(document.read_text(encoding="utf-8"))
        ):
            url = urlsplit(target)
            if (
                document in (readme, root / "README.md")
                and not target.startswith("#")
                and url.scheme not in {"http", "https"}
            ):
                raise ValueError(f"README relative link breaks on PyPI: {target}")
            local: Path | None = None
            if url.scheme:
                prefix = f"/nidops/{project}/blob/"
                if url.netloc == "github.com" and url.path.startswith(prefix):
                    _, _, relative = url.path.removeprefix(prefix).partition("/")
                    local = root / unquote(relative)
            else:
                local = document.parent / unquote(url.path) if url.path else document
            if local is None:
                continue
            if not local.exists():
                raise ValueError(f"{label}: missing link {target}")
            if (
                url.fragment
                and local.suffix == ".md"
                and unquote(url.fragment) not in anchors(local)
            ):
                raise ValueError(f"{label}: missing anchor {target}")
            checked += 1
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            '<!doctype html><meta charset="utf-8"><title>StructWire</title>\n' + html,
            encoding="utf-8",
        )
    print(f"PyPI README renders; {checked} local documentation links/anchors resolve")


if __name__ == "__main__":
    main()
