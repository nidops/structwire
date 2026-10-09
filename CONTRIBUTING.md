# Contributing

Keep StructWire independent of transports, devices and test frameworks. New features
should describe binary layout semantics; see [design](docs/DESIGN.md).

## Development

Create and activate a virtual environment from this checkout (Unix/macOS):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src/structwire
python -m compileall -q src examples tests scripts
python scripts/check_readme.py
```

On Windows, create the environment with `py -3 -m venv .venv` and activate it
in PowerShell with `.venv\Scripts\Activate.ps1`, then use the same `python` commands.
The README checker renders the PyPI description and checks local documentation
links and anchors.

Codec changes need encode/decode tests, meaningful round trips and malformed-input
coverage. Document byte order, width and failure behavior. Update the
[compatibility contract](docs/COMPATIBILITY.md) when changing precision, canonical
output, or schema validation. Add boundary and differential/property tests for
numeric changes.

Pytest executes the Python examples and every Python block in the README and
`docs/`. YAML snippets are parsed and their StructWire schemas compiled; application
routing examples are checked for valid nested layouts. The example routing files
are checked against the supplied catalog. Property tests compare integer and float
bytes with Python's standard library, exercise shared bit fields, and test scaled
integer conversion with biases. Targeted cases cover malformed inputs, duplicate
schemas, and precision loss.

## Coverage

CI reports branch coverage for all `structwire` modules without a percentage gate
or custom exclusions. To inspect the same report locally:

```bash
python -m coverage run --branch --source=structwire -m pytest
python -m coverage report -m
```

The report measures the main test process; subprocess example and resource-limit
checks run separately and are not counted. Review missing behavior, not only the
percentage. Pathological compilation tests use a memory-limited subprocess on
Linux; portable allocation and overlap tests also run on the other platforms.

## Distribution checks

Build into an empty `dist/` directory; move any previous output aside first.

```bash
python -m build
python -m twine check --strict dist/*.whl dist/*.tar.gz
python scripts/check_dist.py dist
python scripts/verify_install.py dist
python scripts/verify_install.py dist --distribution sdist
```

`build` creates the sdist and builds the wheel from it. The configured build and
development tools support SPDX license metadata and core metadata version 2.4.
`check_dist.py` verifies metadata, license/typing files, the single-source version,
public links, and matching package bytes in both artifacts. It prints artifact hashes.

`verify_install.py` creates a fresh environment outside the checkout, installs the
selected distribution and test dependencies, checks imports and metadata under
`python -I`, then runs the full suite from the extracted source distribution.
Tests exercise the installed package without a source-tree import path.

CI runs quality checks and builds once, then tests that wheel on CPython 3.11–3.14
on Linux, Windows, and macOS. The source installation is tested independently.
See [releasing](RELEASING.md) for publication using those artifacts.

## Source material

Contribute only source, schemas, and fixtures that you have the right to publish
under MIT. Use invented, vendor-neutral examples rather than proprietary
identifiers, session tables, packet definitions, logs, or internal names.
Keep private payload catalogs, bench configurations, and credentials out of
this repository. Application-specific routing and payload definitions belong
in the consuming application unless publication rights are explicit.
Automated checks cannot establish those rights.
