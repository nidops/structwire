# Releasing StructWire

Package version lives in `src/structwire/__init__.py`; setuptools derives metadata
from it. Keep this as the single version source.

## Setup

Configure [trusted publishing](https://docs.pypi.org/trusted-publishers/)
separately on TestPyPI and PyPI for project `structwire`, repository
`nidops/structwire`, and workflow `publish.yml`. Use GitHub environments `testpypi`
and `pypi` respectively, restricted to release tags. For a new project, register
a pending publisher; this does not reserve the package name. Confirm account
ownership and public documentation links.

## Release

Before tagging, perform a publication-content review across source, examples,
tests, documentation, and configuration. Check the actual contents of both built
archives, not just their filenames. Ensure example schemas, identifiers, byte
sequences, and names are invented or explicitly cleared for public release.
Automated checks and passing CI do not prove publication rights.

1. Update the package version and documentation.
2. Run the [development checks](CONTRIBUTING.md#development) and
   [distribution checks](CONTRIBUTING.md#distribution-checks).
3. From a clean checkout, tag the reviewed `master` commit as `v<package version>`
   after all supported CI jobs pass. Use `v1.0.0` and verify it with
   `python scripts/check_dist.py dist --tag v1.0.0`.
4. Push the tag, then manually run **Publish** in GitHub Actions with that tag selected.

The workflow reruns CI, uploads verified artifacts to TestPyPI, checks the downloaded
wheel's hash and installation, then publishes the same artifacts to PyPI and verifies
again. Pushes alone do not publish. Check the package page after completion.

If publication fails, rerun failed jobs in the same run while its `release-dist`
artifact is available. Never overwrite tags or uploaded files, or hide mismatches
with `skip-existing`. Changed release contents require a new version.

## Verification

Complete the supported CPython 3.11–3.14 and platform checks, review public API
changes, and test the exact wheel and source distribution before publication.
Building or verifying artifacts does not publish them.
