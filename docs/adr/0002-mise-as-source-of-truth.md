# Use the mise binary as the source of truth

mibare depends on a `mise` binary for registry reverse lookup (`mise registry --json`) and for existence probes (`mise ls-remote <backend string>`), so it tracks mise releases with no snapshot to maintain. It runs mise in an isolated environment (clean environment, temporary `HOME`, `MISE_NO_CONFIG=1`, `GITHUB_TOKEN` passed through), because user settings such as `MISE_DISABLE_BACKENDS` change `mise registry --json` output. We rejected a bundled snapshot of the registry TOMLs and the aqua registry: it would not need a mise binary, but it would need a scheduled refresh job and would lag behind mise.

## Consequences

- A missing or too-old `mise` is a hard error (exit 2), never auto-installed.
- `mise registry --json` is filtered by the host platform and is lossy (no per-backend platforms, version ranges or options), so `--platform` only affects the release-asset check and mibare's own tier rules.
- `mise ls-remote` proves only that a repository exists, not that it can install, so language-package candidates still need the manifest and entrypoint check.
