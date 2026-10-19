# mibare

[![CI](https://github.com/hasansezertasan/mibare/actions/workflows/ci.yml/badge.svg)](https://github.com/hasansezertasan/mibare/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/codecov/c/github/hasansezertasan/mibare)](https://codecov.io/gh/hasansezertasan/mibare)
[![Documentation Status](https://img.shields.io/github/deployments/hasansezertasan/mibare/github-pages?label=docs)](https://hasansezertasan.github.io/mibare)
[![PyPI - Version](https://img.shields.io/pypi/v/mibare.svg)](https://pypi.org/project/mibare)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/mibare.svg)](https://pypi.org/project/mibare)
[![License - MIT](https://img.shields.io/github/license/hasansezertasan/mibare.svg)](https://opensource.org/licenses/MIT)
[![GitHub Stars](https://img.shields.io/github/stars/hasansezertasan/mibare?style=social)](https://github.com/hasansezertasan/mibare/stargazers)
[![Latest Commit](https://img.shields.io/github/last-commit/hasansezertasan/mibare)](https://github.com/hasansezertasan/mibare)

[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![linting - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/hasansezertasan/mibare/badge)](https://scorecard.dev/viewer/?uri=github.com/hasansezertasan/mibare)
[![GitHub Tag](https://img.shields.io/github/tag/hasansezertasan/mibare?include_prereleases=&sort=semver&color=black)](https://github.com/hasansezertasan/mibare/releases/)

[![Downloads](https://pepy.tech/badge/mibare)](https://pepy.tech/project/mibare)
[![Downloads/Month](https://pepy.tech/badge/mibare/month)](https://pepy.tech/project/mibare)
[![Downloads/Week](https://pepy.tech/badge/mibare/week)](https://pepy.tech/project/mibare)

> Mise Backend Resolver: recommends which mise backend to install a GitHub repository with

-----

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Support](#support-heart)
- [Motivation](#motivation)
- [Features](#features)
- [Author](#author-person_with_crown)
- [Analysis](#analysis)
- [Contributing](#contributing-heart)
- [Development](#development-toolbox)
- [Releasing](#releasing)
- [Credits](#credits)
- [License](#license-scroll)
- [Changelog](#changelog-memo)

## Installation

`mibare` is a standalone end-user tool whose primary command is `mibare`. Install it into an isolated environment:

```console
uv tool install mibare
```

Or run it without installing with `uvx mibare`. See the [installation docs](https://hasansezertasan.github.io/mibare/installation.html) for pipx and from-source options.

Install with [Homebrew](https://brew.sh) (macOS/Linux):

```sh
brew install hasansezertasan/tap/mibare
```

Install with [Scoop](https://scoop.sh) (Windows):

```sh
scoop bucket add hasansezertasan https://github.com/hasansezertasan/scoop-bucket
scoop install hasansezertasan/mibare
```

### Verify the installation

The package root is importable after installation:

```pycon
>>> from mibare import __doc__
>>> isinstance(__doc__, str)
True

```

## Usage

### CLI

```bash
mibare BurntSushi/ripgrep
mibare https://github.com/BurntSushi/ripgrep
mibare --help
```

The registry's backends for the repository are printed in registry order, the
first marked as the recommendation. Exit code 0 means a recommendation was
found, 1 that no backend was found, and 2 an error (input that is not a GitHub
repository, or a missing or too-old `mise`; 2026.10.13 or newer is required).

## Support :heart:

If you have any questions or need help, feel free to open an issue on the [GitHub repository][mibare].

## Motivation

A mise user who finds a tool on GitHub has no way to learn which mise backend to install it with. `mise use` accepts `owner/repo` but does not say which backend it chose, and its interactive selector only lists tools already in the mise registry. mibare takes a GitHub repository and recommends a backend (`aqua:`, `github:`, `pypi:`, `cargo:`, `npm:` or `go:`), ranked by mise's documented tier ladder, with legacy backends flagged. Terms follow the [glossary](./GLOSSARY.md); design decisions are in [`docs/adr/`](./docs/adr).

## Features

- **Library core**: an importable package holding the resolution logic.
- **CLI**: a thin Typer wrapper around the library, run as `mibare`.

## Author :person_with_crown:

This project is maintained by [Hasan Sezer Taşan][author], It's me :wave:

## Analysis

- [Snyk Python Package Health Analysis](https://snyk.io/advisor/python/mibare)
- [Libraries.io - PyPI](https://libraries.io/pypi/mibare)
- [Safety DB](https://data.safetycli.com/packages/pypi/mibare)
- [PePy Download Stats](https://www.pepy.tech/projects/mibare)
- [PyPI Download Stats](https://pypistats.org/packages/mibare)
- [Pip Trends Download Stats](https://piptrends.com/package/mibare)
- [PyPI Map Dependency Graph](https://pypimap.com/package/mibare)

## Contributing :heart:

Any contributions are welcome! Please follow the [Contributing Guidelines](./.github/CONTRIBUTING.md) to contribute to this project.

## Development :toolbox:

See the [Contributing Guidelines](./.github/CONTRIBUTING.md#your-first-code-contribution)
for local setup, the common development tasks (exposed via [mise](https://mise.jdx.dev)),
building and previewing the documentation, and the VS Code debugging configurations.

## Releasing

Versioning and releases are automated with [release-please](https://github.com/googleapis/release-please), driven by [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/) PR titles squash-merged into `main`. release-please maintains a release PR that bumps the version and `CHANGELOG.md`; merging it tags the release and publishes to PyPI. See the [Contributing Guidelines](./.github/CONTRIBUTING.md#releasing) for the commit conventions, and the [Repository setup](./docs/maintaining/setup.rst) guide for one-time configuration and optional post-launch integrations such as a social preview, downstream packaging, and Repology.

Pause merges that change `.github/workflows/`, including Renovate action-pin updates, from merging a release PR until the entire Release run finishes. Workflow differences between the release commit and current `main` can block tag or release creation with a 403 when using `GITHUB_TOKEN`. See [Release recovery](./docs/maintaining/setup.rst#keep-workflow-changes-out-of-an-active-release) for prevention and recovery steps.

For adoption or template-update reconciliation, ask your agent to "audit this
template adoption/update against our existing project behavior".
The shipped [template-adoption skill](./.claude/skills/template-adoption/SKILL.md)
also supports audits after an update was applied. It compares workflow behavior,
required checks, custom tooling, and documentation, and asks before consequential
cleanup. Its prek-workflow example shows why duplicate commands alone do not
justify removing a workflow. Use the sibling `repo-setup` skill for repository
settings and release setup.

## Credits

This package was created with [Copier](https://github.com/copier-org/copier) and the [hasansezertasan/copier-pyproject](https://github.com/hasansezertasan/copier-pyproject) project template.

## License :scroll:

This project is licensed under the [MIT License](https://spdx.org/licenses/MIT.html).

## Changelog :memo:

For a detailed list of changes, please refer to the [CHANGELOG](./CHANGELOG.md).

<!-- Refs -->
[author]: https://github.com/hasansezertasan
[mibare]: https://github.com/hasansezertasan/mibare
