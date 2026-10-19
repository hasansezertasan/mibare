# How mise models and chooses backends

Retrieved 2026-10-18. Source tree: `jdx/mise` at commit `2866bb93824ff4d76ada6d453a42d4409074a1fc` (HEAD of main, 2026-10-18; latest tag `v2026.10.14`, `Cargo.toml` version 2026.10.14). Local mise used for CLI output: 2026.10.13.

Citation convention: `repo:path` means a file in the jdx/mise clone at the commit above (browsable at `https://github.com/jdx/mise/blob/2866bb9/<path>`). Docs pages are cited by their published URL on mise.jdx.dev. The text was read from the `docs/` source in the same clone, not fetched live from the site. The URL-to-file mapping follows the page links inside the docs themselves, and I did not diff the live site against the clone.

## Summary

- mise has about 20 backend types. A backend is a "source to install from", written as `backend:tool[options]`. The registry maps a short name to an ordered list of such identifiers.
- Short-name resolution is a fixed precedence chain: `MISE_BACKENDS_<TOOL>`, then `[tool_alias]`, then `[plugins]` URL, then the lockfile, then an installed plugin, then the first eligible registry backend. Eligible means it runs on this platform, is not in `disable_backends`, is not experimental-gated, and covers the requested version.
- The docs recommend this order: packslip, then aqua, then github/gitlab/forgejo, then http/s3, then language-package backends, then plugins. `ubi` is deprecated (removal in 2027.1.0). `asdf` is legacy and never used on Windows. `vfox` is a plugin backend, and new `asdf`, `vfox` and `ubi` registry entries are rejected.
- Machine-readable sources: `registry/*.toml` (with a JSON Schema), `mise registry --json` (lossy), `mise tool <name> --json` (resolved backend plus security), the hosted `https://mise.jdx.dev/registry/latest.tar.zst` archive, and mise-versions `data/<tool>.toml` and `data/index.v1.json`. None of the hosted ones has a documented stability guarantee, except that mise-versions index.v1 carries a `format` field.
- Gaps and ambiguities are listed in section 5. The main ones are that the JSON output drops per-backend platforms, version ranges and options, and that the registry order is "preference", not "quality".

## 1. Backends mise supports

**Enumeration in source.** The `BackendType` enum is: aqua, asdf, cargo, conda, core, dotnet, forgejo, gem, github, gitlab, go, npm, packslip, pipx (displayed and serialized as `pypi`, with `pipx` accepted as an input alias), spinel, spm, http, s3, ubi, vfox, plus `VfoxBackend(plugin_name)` and `Unknown`. (`repo:src/backend/backend_type.rs`)

**`mise backends ls`** printed, on the 2026.10.13 binary: aqua, asdf, cargo, conda, core, dotnet, forgejo, gem, github, gitlab, go, npm, packslip, pypi, spinel, spm, http, s3, ubi, vfox. (local run; verified)

**Syntax.** `<backend>:<tool-name-within-backend>[@version]`, with optional tool options in brackets, for example `'pypi:black[extras=jupyter]'`. Any identifier works in `mise.toml` without a registry entry. The registry only adds short names. Core tools use `core:` (for example `core:node`). Source: <https://mise.jdx.dev/dev-tools/backends/#identifiers>s>s>s>s>s>

**Prefix parsing.** `BackendType::guess` takes the text before the first `:` and maps it as above. Anything else is `Unknown`. (`repo:src/backend/backend_type.rs`)

**Experimental gate.** `dotnet`, `packslip`, `s3`, `spinel` and `spm` consult an `EXPERIMENTAL` constant (`BackendType::is_experimental`). Registry-driven selection skips a backend whose constant is true unless `experimental = true`. (`repo:src/backend/backend_type.rs`, `repo:src/registry.rs` `eligible_entries`.) The values of those constants are not shown above. The docs list only spinel as "(experimental)". Which of the five are currently gated is **unverified**.

Table, from <https://mise.jdx.dev/dev-tools/backends/#which-backend-to-use>e>e>e>e>e> (docs status wording quoted):

| Backend | Installs | Example | Docs status |
|---|---|---|---|
| packslip | releases with signed manifests | `packslip:github.com/jdx/hk` | first preference |
| aqua | release assets described by the aqua registry | `aqua:BurntSushi/ripgrep` | preferred |
| github / gitlab / forgejo | release assets from a forge | `github:BurntSushi/ripgrep` | preferred (same tier as aqua) |
| http / s3 | archives at URLs you provide | `http:my-tool` with a `url` option | S3 also needs AWS credentials |
| cargo, go, npm, pypi (alias `pipx:`), gem, dotnet, spm | language packages | `cargo:eza`, `npm:prettier`, `pypi:black`, `gem:rubocop`, `dotnet:GitVersion.Tool`, `spm:nicklockwood/SwiftFormat`, `go:github.com/DarthSim/hivemind` | needs the language runtime or toolchain |
| conda | conda packages and their dependencies | `conda:ffmpeg` | needs nothing else |
| spinel | Ruby compiled to native executables | `spinel:tobi/try` | experimental |
| vfox | Lua plugin | `vfox:version-fox/vfox-cmake` | works on Windows; use when custom logic is needed |
| asdf | shell-script plugin | `asdf:MetricMike/asdf-awscli` | legacy; not available on Windows |
| ubi | GitHub and GitLab release assets | `ubi:BurntSushi/ripgrep` | deprecated; removed in 2027.1.0 |
| core | tools built into mise | `core:node` | see <https://mise.jdx.dev/core-tools.html>l>l>l>l>l> |

Deprecation and legacy facts:

- `ubi:` has warned since 2026.4.0 and is removed in 2027.1.0. Migration is `ubi:` to `github:`, `gitlab:`, or an `http:` tool. <https://mise.jdx.dev/dev-tools/backends/ubi.html>l>l>l>l>l> (`repo:docs/dev-tools/backends/ubi.md`)
- asdf plugins are "shell scripts that run with your permissions". The docs say to prefer backends that install a publisher's release directly. <https://mise.jdx.dev/dev-tools/backends/asdf.html>l>l>l>l>l> (`repo:docs/dev-tools/backends/asdf.md`)
- `pipx:` is another name for `pypi:`, which uses uv, or pipx when uv is unavailable. <https://mise.jdx.dev/dev-tools/backends/pypi.html>l>l>l>l>l> (`repo:docs/dev-tools/backends/pypi.md`)

**Plugin-provided backends.** A vfox backend plugin supplies its own prefix (`VfoxBackend(name)`), and `disable_backends` can name it. (`repo:src/backend/backend_type.rs` `disable_key`; `repo:settings.toml` `[disable_backends]` docs.) Backend plugin authoring: <https://mise.jdx.dev/backend-plugin-development.html>l>l>l>l>l>. I did not read that page, so the details of how third-party prefixes interact with the registry are **unverified**.

## 2. Registry mapping, ordering and user overrides

**Registry shape.** One file per tool, `registry/<name>.toml`, where the file name is the short name. `backends` is an ordered list of strings or tables, "in order of preference". `version_order` is required (`semver` or `source`). Source: <https://mise.jdx.dev/contributing/registry.html#registry-format>t>t>t>t>t> (`repo:docs/contributing/registry.md`) and `repo:schema/mise-registry-tool.json` (`required: ["backends", "version_order"]`).

Examples at the commit above (`repo:registry/`):

- `jq.toml`: `["aqua:jqlang/jq", "asdf:mise-plugins/asdf-jq"]`
- `ripgrep.toml`: `aliases = ["rg"]`, backends `["aqua:BurntSushi/ripgrep", "asdf:https://gitlab.com/wt0f/asdf-ripgrep", "cargo:ripgrep"]`
- `node.toml`: `["core:node"]`, with `bins`, `detect` and `idiomatic_files`

**Size and distribution** (computed from `mise registry --json` on 2026.10.13). 1067 rows, which include aliases as their own rows, and 1015 `registry/*.toml` files in the repo. 756 rows have more than one backend. Backend frequency across all lists: aqua 716, asdf 622, github 254, cargo 89, vfox 58, npm 55, pypi 32, go 25, conda 22, http 18, packslip 14, core 14, gem 3, spm 2, gitlab 1. Backend in first position: aqua 699, github 188, vfox 42, npm 41, pypi 23, conda 20, http 16, packslip 14, core 14, go 4, gem 3, spm 1, gitlab 1, cargo 1. These counts are a point-in-time computation and the registry changes with every release.

**Per-backend entry fields** (`RegistryBackend`, `repo:src/registry.rs`; `repo:schema/mise-registry-tool.json`): `full`, `platforms` (`linux`/`macos`/`windows`, `x64`/`arm64`, or `os-arch`; Windows arm64 also matches x64 selectors), `min_version` (inclusive), `max_version` (exclusive), `attestations_since`, `options`. Bounds require `version_order = "semver"`. Source: <https://mise.jdx.dev/contributing/registry.html#backend-entries>s>s>s>s>s> and #minimum-backend-versions. In the clone, 35 files use `platforms`, 17 use `min_version` or `max_version`, and 7 use `deprecated`. These come from `grep -l` over `registry/*.toml`.

**Tool-level fields:** `aliases`, `bins`, `description`, `detect`, `idiomatic_files`, `os`, `overrides`, `test`, `url`, `deprecated`, `version_order`.

**Selection order for a short name** (<https://mise.jdx.dev/dev-tools/backends/#how-backend-selection-works>s>s>s>s>s>). An identifier with a prefix always uses that backend. Otherwise the first of these applies:

1. `MISE_BACKENDS_<TOOL>` environment variable (tool name uppercased, `-` to `_`; `repo:src/registry.rs` `env_backend_override`).
2. `[tool_alias]` entry naming a backend, such as `node = "core:node"` (<https://mise.jdx.dev/dev-tools/aliases.html>l>l>l>l>l>).
3. A plugin URL for the tool under `[plugins]`.
4. The backend recorded in `mise.lock`, when it can serve the requested version.
5. An installed plugin with the same name, unless its backend is disabled.
6. The first registry backend that runs on this platform, is not in `disable_backends`, supports the requested version, and, if experimental, only with `experimental = true`.

**Code check of step 6.** `eligible_entries` in `repo:src/registry.rs` filters in registry order by: `keep`, then `backend_matches_platform`, then membership in the set of all `BackendType` names minus `Settings.disable_backends` (and minus `asdf` on Windows, hard-coded, "whatever this setting says"), then the experimental gate. Duplicates are collapsed to the first position.

**Version-specific selection.** Entries with `min_version` or `max_version` are checked against the request. Exact versions are compared, and numeric prefixes are excluded only when wholly outside the range. `latest` and prefixes that span a boundary "keep the normal order". These boundaries apply only to short names. An explicit identifier ignores them. A failed download or signature check does not fall back to the next backend. Source: <https://mise.jdx.dev/dev-tools/backends/#version-specific-backends>s>s>s<https://mise.jdx.dev/contributing/registry.html#minimum-backend-versions>ons>ons>ons>ons>ons>. Code: `RegistryBackend::supports_version` in `repo:src/registry.rs`.

**Settings that alter resolution:**

- `disable_backends` (env `MISE_DISABLE_BACKENDS`, comma list; default `[]`). Disabled backends are skipped for short names, and installing an explicit identifier on one fails. Already-installed versions stay on disk. A vfox plugin can be disabled by plugin name. `repo:settings.toml` `[disable_backends]`; <https://mise.jdx.dev/dev-tools/backends/#disable-backends>s>s>s>s>s>
- `disable_default_registry` (`MISE_DISABLE_DEFAULT_REGISTRY`): "Stop mapping short names such as `php` to the asdf and vfox plugins listed in the registry." The wording is narrow. I did not trace what it does to the other backends in the registry, so the exact semantics are **unverified**. `repo:settings.toml`
- `experimental` (gates experimental backends).
- `registry_floating` (default off), `registry_cache_ttl`, `aqua.baked_registry`, `aqua.registries`, `aqua.registry_cache_ttl`. See section 4.
- `MISE_BACKENDS_<TOOL>` and `[tool_alias]`, as above.
- `mise use` writes the identifier to `[tools]` as given, for example `"aqua:BurntSushi/ripgrep" = "latest"`, so using the short name stores the short name and re-resolves through the chain above. `mise backends switch` rewrites lock entries to the registry's current backend. <https://mise.jdx.dev/dev-tools/backends/>/>/>/<https://mise.jdx.dev/cli/backends/switch.html>tml>tml>tml>tml>tml>. I did not read the `mise use` source to confirm that it never rewrites a short name into an identifier. That is **unverified** beyond the docs example.

**Options attached to a short name.** A shorthand can set backend options. The docs' example is `aws-cli`, which uses `aqua:aws/aws-cli` with `symlink_bins = true`. Writing the identifier yourself does not apply those options, so short name and identifier are not equivalent. <https://mise.jdx.dev/registry.html#options-a-shorthand-sets>s>s>s>s>s>

**Debug commands:** `mise tool <name> --backend`, `mise registry <name>`, `mise plugins ls`, `mise config ls`, `mise ls --current`. <https://mise.jdx.dev/dev-tools/backends/#troubleshooting>g>g>g>g>g>. Local check: `mise tool ripgrep --backend` printed `aqua:BurntSushi/ripgrep`.

## 3. Documented guidance for choosing among backends

- **Preference ladder.** "Start with the tool's registry short name. When you choose a backend yourself, prefer one that installs the publisher's own prebuilt release", ordered: (1) packslip, (2) aqua, or github, gitlab, forgejo, (3) http, s3, (4) language package backend, when the tool ships only as a package or you need package options, (5) a plugin only when custom logic is needed. <https://mise.jdx.dev/dev-tools/backends/#which-backend-to-use>e>e>e>e>e>
- **Registry acceptance tiers** (for new entries only, "you can use any backend in your own config"): tier 1 packslip. Tier 2 aqua, github, gitlab. Tier 3 conda ("high bar"). Tier 4 npm, pypi, gem, cargo, go, dotnet ("very high bar", needs maintainer agreement beforehand). Not accepted for new entries: asdf, vfox, ubi, "for supply-chain security reasons". http is untiered and accepted only with a `version_list_url`. forgejo, s3, spm and spinel are not covered by the tiers. <https://mise.jdx.dev/contributing/registry.html#backend-acceptance-tiers>s>s>s>s>s>
- **aqua over github when the tool is in the aqua registry.** "its recipes carry per-version logic and SLSA and other verification metadata". Use github for tools not in aqua but with GitHub releases. Same page.
- **Go and Rust tools** "usually ship single binaries, so prefer a tier 1 or 2 backend for them". Same page.
- **Windows.** aqua "works on Windows". asdf is never selected on Windows, and `asdf:` tools are skipped. vfox runs on Windows. <https://mise.jdx.dev/dev-tools/backends/aqua.html>l><https://mise.jdx.dev/dev-tools/backends/asdf.html>tm<https://mise.jdx.dev/dev-tools/backends/vfox.html>.html>.html>.html>.html>.html>. No explicit Windows statement was found for github, gitlab, http, npm, cargo, pypi or conda, so their status is **unverified**.
- **Security and verification.** "Verification differs by backend and by tool", and a backend can check a signature or provenance only when the publisher provides one. Checks per backend (<https://mise.jdx.dev/security.html#download-verification>n>n>n>n>n>): aqua gives checksums, Cosign, Minisign, SLSA and GitHub attestations as declared by the aqua recipe. github gives GitHub attestations when published, and SLSA when a signer is named. packslip gives a signed manifest, digests and a pinned signer. Node, Swift, Zig and precompiled Ruby and Python have their own checks. The page lists no checks for http, s3, cargo, npm, pypi, go, gem, conda or dotnet, which most naturally reads as "none documented", but that is an inference and **unverified**. Per-tool results are visible via `mise tool <name>` (Security line) and `mise registry --json --security`.
- **Provenance can be required.** A registry entry can set `attestations_since`, from which version a missing GitHub attestation is treated as a downgrade (github backends only). `repo:schema/mise-registry-tool.json`, `repo:src/registry.rs`.
- **Speed.** I found no documented per-backend speed ranking. The docs only note that language backends need their toolchain, that cargo uses cargo-binstall for prebuilt binaries, and that `mise registry --json --security` is slow for a full listing. The speed question is **unverified or undocumented**. mise-versions exists to avoid GitHub's anonymous rate limit (`repo:settings.toml` `[use_versions_host]`), which affects version listing, not install speed.
- **aqua vs ubi vs asdf.** The docs steer away from ubi (deprecated) and asdf (legacy, shell code, not Windows). The registry's own data still has many asdf entries (622 backend occurrences, always as non-first fallbacks per `mise registry` order in the sampled tools). I did not check that asdf is never first. In the counted data, asdf is not among the first-position counts.

## 4. Machine-readable sources

1. **`registry/*.toml` in jdx/mise.** The authoritative source, bundled into each release. The schema is `schema/mise-registry-tool.json` (JSON Schema, `unevaluatedProperties: false`; `required: backends, version_order`; backend table keys `full`, `platforms`, `min_version`, `max_version`, `attestations_since`, `options`). `mise run lint` validates files against it, and the build fails on unreadable entries. <https://mise.jdx.dev/registry.html>l><https://mise.jdx.dev/contributing/registry.html#registry-format>mat>mat>mat>mat>mat>. Stability: the schema is versionless, in-repo and changes with mise. No compatibility promise is documented (**unverified** beyond that).

2. **`mise registry --json`.** Rows have `short`, `backends` (strings only, in preference order), `bins`, `description`, `url`, `aliases`, and `security` (only with `--security`, which requires `--json`). Optional fields are omitted when empty. `mise registry <name> --json` gives one object, and `mise registry --backend <b>` filters. Source: `repo:src/cli/registry.rs` (`RegistryToolOutput`) and <https://mise.jdx.dev/cli/registry.html>l>l>l>l>l>. Observed on 2026.10.13: aliases appear as separate rows, with the full alias list repeated on each. A resolver should dedupe by `short` against `aliases` or use `--hide-aliased` (a flag, though I did not test it with `--json`). The output is lossy: it does **not** include per-backend `platforms`, `min_version`, `max_version`, `options`, `os`, `deprecated`, `version_order`, `overrides` or `detect`. Note also that `rt.backends()` is the already-filtered view, so the CLI list reflects the local platform and settings. The code at `src/registry.rs:816` suggests this, but I did not read the function body, so this is **unverified**. If so, `mise registry --json` depends on the machine that runs it (OS, `disable_backends`, `experimental`).

3. **`mise tool <name> --json`.** Gives the resolved `backend` for this machine and config, plus `description`, `url`, installed and requested versions, `tool_options`, and `security` entries (for example `{"type":"checksum","algorithm":"sha256"}` and `{"type":"github_attestations","signer_workflow":"..."}`). Local run, jq, 2026.10.13. This is the ground truth for "what would mise pick here", but it needs a mise binary.

4. **Hosted registry archive.** `https://mise.jdx.dev/registry/latest.tar.zst` (HTTP 200, 94,279 bytes on 2026-10-18). It contains `registry/<name>.toml` files. mise downloads it only when `registry_floating = true`. mise caps entries at 4096, 1 MiB per entry and 16 MiB total, and requires version-order metadata. `repo:src/registry.rs` (`MISE_REGISTRY_ARCHIVE_URL`, `parse_registry_archive`), <https://mise.jdx.dev/registry.html#floating-registries>s>s>s>s>s>. This is the best hosted, no-binary source. The URL is hard-coded in the client but not documented as a public API, so its stability is **unverified**. `https://mise.jdx.dev/registry.json` returned 404, so no hosted registry JSON exists at that path.

5. **Bundled aqua registry.** `vendor/aqua-registry/registry.yml` (about 2,147 `- type:` lines) plus `metadata.json` pinning `aquaproj/aqua-registry` at tag `56d6f7647505550d2f47dbed308b676085302db5`. mise reads recipes for `aqua:` and does verification and platform checks from `supported_envs`. <https://mise.jdx.dev/dev-tools/backends/aqua.html>l>l>l>l>l>. The upstream is `https://github.com/aquaproj/aqua-registry`. I did not read the upstream aqua docs for its schema and stability, so those are **unverified**. Users can add registries via `aqua.registries`, and `registry_floating` also fetches the current official one. `repo:settings.toml` `[aqua.registries]`.

6. **mise-versions (`https://mise-versions.jdx.dev`).** Used by mise for version lists, public GitHub release data and attestations. `repo:src/versions_host.rs` shows `/data/<tool>.toml` (a `[versions]` table of version to `{created_at, prerelease?}`) and `/t?tool=...` (an install tracking beacon, not a data API). `repo:src/versions_index.rs` shows `/data/index.v1.json` with a `format` header (client accepts only 1), about 140 KB compressed per its comments, and a contract in `docs/versions-index.md` of jdx/mise-versions (not read). `data/node.toml` returned 200 on 2026-10-18. `/api/` returned 404. This is version data, not backend-resolution data. It is useful for "does this backend list versions", but mise-versions is keyed by tool short name, and I did not verify per-backend coverage. The `use_versions_host` setting controls it. `repo:settings.toml`. Docs also say it carries security information per tool. <https://mise.jdx.dev/registry.html#tools>s>s>s>s>s>. How to query that is **unverified**.

7. **Docs registry page data.** `docs/registry.data.ts` and the `Registry` Vue component build <https://mise.jdx.dev/registry.html>l>l>l>l>l>. I did not inspect whether they expose a JSON file, so that is **unverified**.

## 5. Open questions for the design interview

1. **What does "resolve" return?** Options are: (a) mise's own pick (`mise tool --backend` semantics, reproduce the six-step chain), (b) the registry's preference list, or (c) a recommendation with reasons (security, platform). The docs' ladder (packslip, aqua, forge, ...) differs from the raw registry order in some entries, because older entries put vfox or asdf first (42 first-position vfox entries exist) and 1 puts cargo first.
2. **Should mibare follow mise's order or re-rank?** The registry order is a curated "preference", but it carries legacy entries. Should the resolver apply the documented tiers on top and warn on asdf, vfox and ubi?
3. **Inputs beyond short names.** Handle user-supplied `owner/repo`, URLs, package names (`npm:`, `pypi:`), aliases such as `rg`, and tools missing from the registry (fall back to aqua registry lookup, then github)? The registry is explicitly "not a list of every tool mise can install", while the aqua registry has far more recipes.
4. **Platform and config context.** Selection depends on OS and arch, `disable_backends`, `experimental`, version request, lockfile, aliases and env overrides. Should mibare take a target platform and settings as input, or ignore them? Hard-coded rule: asdf is excluded on Windows.
5. **Data source choice and freshness.** Bundle a registry snapshot, fetch `latest.tar.zst` (undocumented URL, but used by mise itself), shell out to `mise registry --json` (lossy and machine-dependent), or read the git repo? Pinning to a mise version matters because the schema evolves (for example `min_version`, `max_version` and `attestations_since` are recent).
6. **Version-range-dependent backends.** The JSON CLI hides `min_version` and `max_version`. If the resolver must answer "for `hk@1.57` which backend?", it needs the TOML, not the JSON.
7. **Short name vs identifier equivalence.** Registry options (`symlink_bins`, `allow_builds`, per-platform URLs) are only applied via the short name. Should the output include the options and the short name, or only the identifier?
8. **Security data.** `mise tool --json` and `registry --json --security` expose checks per backend, but only through a binary, and "badges come from registry metadata, so a check may apply only to some versions or platforms". How much of this should mibare surface, and should it rank by it?
9. **Deprecation timeline.** ubi removal in mise 2027.1.0. The registry still contains `ubi:` entries? I did not count them: the `ubi` prefix does not appear in the counted backend list, so possibly none remain. That is consistent with the data, but it is an inference from absence in one run.
10. **Unverified items worth confirming:** which backends are currently experimental-gated; exact semantics of `disable_default_registry`; third-party backend plugin prefixes in the registry; speed guidance (none found); `mise use` writing a short name vs identifier; stability promises for `latest.tar.zst`, `mise registry --json` and mise-versions endpoints; Windows status for non-aqua/asdf/vfox backends.
