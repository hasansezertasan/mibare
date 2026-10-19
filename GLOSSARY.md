# mibare

Mise Backend Resolver. Given a GitHub repository, it recommends which mise backend to install the tool with.

## Language

**Backend**:
The mechanism mise uses to find, download and install a tool, named by a prefix such as `aqua:`, `github:` or `cargo:`.
_Avoid_: Provider, installer, source

**Backend string**:
A backend plus its tool identifier in mise's `backend:tool` form, such as `aqua:BurntSushi/ripgrep`.
_Avoid_: Backend ID, package spec

**Tool**:
A program or runtime that mise can install and manage.
_Avoid_: Package, plugin

**Repository**:
The GitHub `owner/repo` that mibare is asked about, given as a URL or the `owner/repo` shorthand.
_Avoid_: Repo URL (as a concept), project

**Registry**:
Mise's curated mapping from a short tool name to an ordered list of backend strings.
_Avoid_: Catalog, index

**Candidate**:
A backend string that could install the tool for a given repository, found at one step of the resolution ladder.
_Avoid_: Option, match

**Resolve**:
To turn a repository into a ranked list of candidates with one marked as the recommendation.
_Avoid_: Detect, look up

**Recommendation**:
The top-ranked candidate, shown with its backend string, a ready-to-paste `mise use` command and short reasons.
_Avoid_: Pick, answer

**Entrypoint**:
The installable executable a repository's root manifest declares (a Python script, a Rust bin target, an npm `bin`, a Go `package main`). Its presence is what makes a language-package backend a candidate.
_Avoid_: Binary, command, script

**Tier**:
A position on mise's documented backend preference ladder, used to rank candidates.
_Avoid_: Priority, score

**Legacy backend**:
A backend that mise documents as discouraged or deprecated (`asdf`, `vfox`, `ubi`). Candidates using one are flagged with a warning.
_Avoid_: Old backend, deprecated backend
