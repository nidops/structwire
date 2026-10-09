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
   after all supported CI jobs pass. For `0.1.0.post1`, use `v0.1.0.post1` and verify
   it with `python scripts/check_dist.py dist --tag v0.1.0.post1`.
4. Push the tag, then manually run **Publish** in GitHub Actions with that tag selected.

The workflow reruns CI, uploads verified artifacts to TestPyPI, checks the downloaded
wheel's hash and installation, then publishes the same artifacts to PyPI and verifies
again. Pushes alone do not publish. Check the package page after completion.

If publication fails, rerun failed jobs in the same run while its `release-dist`
artifact is available. Never overwrite tags or uploaded files, or hide mismatches
with `skip-existing`. Changed release contents require a new version.

## Replacing an existing release

`0.1.0.post1` replaces the examples, documentation and test fixtures shipped in
`0.1.0` while preserving library behavior. Publish and verify the replacement on
both indexes before retiring the earlier release. Consumers with exact `==0.1.0`
pins must update them; a post-release cannot satisfy that exact pin.

[Yanking](https://docs.pypi.org/project-management/yanking/) leaves files available
to exact pins and direct downloads. If the old files must be removed, delete the
old release separately on PyPI and TestPyPI after verifying the replacement.
[Deleted filenames cannot be reused](https://pypi.org/help/#file-name-reuse).
Deleting an index release does not remove Git tags, branches, source archives,
or copies already downloaded. Keep recovery branches local when retiring public
history, and review old public refs separately.
