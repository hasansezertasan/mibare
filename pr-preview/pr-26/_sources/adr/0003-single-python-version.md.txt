# Target a single Python version

mibare requires Python 3.14 (`requires-python = ">=3.14"`) and tests only 3.14. It is an application, not a library: users run it through `uvx`, `pipx` or mise's `pypi:` backend, each of which provisions its own interpreter, so a wide supported range buys them nothing and costs a tox/CI matrix, a `tomli` backport and type-checker targets pinned to the oldest version. The importable core from [ADR 0001](0001-python-with-uv-and-library-core.md) is an architectural seam for a future front end, not a promise to support other projects importing it on older interpreters. We rejected keeping 3.10+ for a hypothetical library audience, and rejected pinning `==3.14.*`: the lower bound stays open so newer interpreters are not blocked, and a new version is added to the classifiers and CI matrix only once it is tested.

## Consequences

- Classifiers list 3.14 and CPython only; PyPy is dropped because it has no 3.14 yet.
- Code may use 3.14 features, and ruff, mypy, basedpyright, ty, pyrefly and prek all target 3.14.
- `copier-pyproject` assumes a multi-version matrix, so a `copier update` may try to restore the old versions; reject those hunks.
- Reopen this decision if mibare is published as a library with outside importers.
