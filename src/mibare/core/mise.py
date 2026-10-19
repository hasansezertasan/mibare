"""The mise adapter: the only code that runs a ``mise`` binary (ADR 0002).

``mise`` always runs in an isolated environment so the user's settings, such as
``MISE_DISABLE_BACKENDS``, never change the answer: a clean environment, a
temporary ``HOME``, ``MISE_NO_CONFIG=1``, and ``GITHUB_TOKEN`` plus the proxy and
certificate variables passed through so mise can still reach the network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from mibare.core.errors import MiseError, MiseNotFoundError, MiseTooOldError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: User variables that reach mise: the token and what the network needs, never
#: mise's own settings. mise only honours proxies set in the environment that
#: starts it (https://mise.jdx.dev/faq.html#how-do-i-use-mise-with-http-proxies).
_PASSTHROUGH = (
    "GITHUB_TOKEN",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)

__all__ = ["MIN_MISE_VERSION", "Mise", "RegistryEntry", "SubprocessMise", "run_process"]

#: The oldest mise whose ``registry --json`` output mibare understands.
MIN_MISE_VERSION = (2026, 10, 13)

_INSTALL_URL = "https://mise.jdx.dev/getting-started.html"
_TIMEOUT_SECONDS = 60
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
#: What ``mise ls-remote`` prints (checked against mise 2026.10.14) when the
#: recipe does not exist: an aqua backend with no registry entry, or a
#: ``github:`` repository that answers 404. Any other failure, such as a
#: network error or a rate limit, says nothing about whether the recipe exists.
_ABSENT = re.compile(r"no aqua-registry found for|GitHub repository \S+ not found")


class Runner(Protocol):
    """Runs a command with exactly the given environment, in a directory."""

    def __call__(
        self, args: Sequence[str], env: Mapping[str, str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        """Run ``args`` and return the finished process."""
        raise NotImplementedError


@dataclass(frozen=True)
class RegistryEntry:
    """One tool in mise's registry.

    Attributes:
        tool: The registry's short name for the tool.
        backends: The tool's backend strings, in registry order.
    """

    tool: str
    backends: tuple[str, ...]


class Mise(Protocol):
    """The interface ``resolve()`` needs from mise, replaceable in tests."""

    def version(self) -> str:
        """Return the mise version, after checking it meets the minimum."""
        raise NotImplementedError

    def registry(self) -> tuple[RegistryEntry, ...]:
        """Return the registry entries in registry order."""
        raise NotImplementedError

    def recipe_exists(self, backend_string: str) -> bool:
        """Say whether mise can list versions of ``backend_string``.

        Raises:
            MiseError: If the probe failed for a reason other than the recipe
                being absent, such as a network failure.
        """
        raise NotImplementedError


def run_process(
    args: Sequence[str], env: Mapping[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run a command with exactly ``env`` as its environment.

    The executable is looked up on the caller's ``PATH``, not on ``env``.

    Args:
        args: The command and its arguments.
        env: The complete environment for the process.
        cwd: The directory to run in.

    Returns:
        subprocess.CompletedProcess[str]: The finished process.

    Raises:
        FileNotFoundError: If the executable is not on ``PATH``.
    """
    executable = shutil.which(args[0])
    if executable is None:
        raise FileNotFoundError(args[0])
    return subprocess.run(  # noqa: S603
        [executable, *args[1:]],
        env=dict(env),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def _entry(item: object) -> RegistryEntry | None:
    """Read one ``mise registry --json`` item.

    Args:
        item: One element of the decoded JSON array.

    Returns:
        RegistryEntry | None: The entry, or ``None`` if the item lacks a string
            ``short`` or a list of string ``backends``.
    """
    if not isinstance(item, dict):
        return None
    fields = cast("dict[str, object]", item)
    short = fields.get("short")
    backends = fields.get("backends")
    if not isinstance(short, str) or not isinstance(backends, list):
        return None
    names = cast("list[object]", backends)
    if not all(isinstance(name, str) for name in names):
        return None
    return RegistryEntry(short, tuple(cast("list[str]", names)))


class SubprocessMise:
    """The real adapter, which runs ``mise`` as a subprocess."""

    def __init__(self, run: Runner = run_process) -> None:
        """Create the adapter.

        Args:
            run: Runs the command line; replaced in tests so no process starts.
        """
        self._run: Runner = run
        self._version: str | None = None

    def version(self) -> str:
        """Return the mise version, recording it on first use.

        Returns:
            str: The version number, such as ``2026.10.13``.

        Raises:
            MiseTooOldError: If mise is older than ``MIN_MISE_VERSION``.
            MiseError: If the version cannot be read.
        """
        if self._version is None:
            reported = self._execute("--version")
            match = _VERSION.match(reported.strip())
            if match is None:
                message = f"Could not read the mise version from {reported!r}."
                raise MiseError(message)
            found = tuple(int(part) for part in match.groups())
            number = ".".join(match.groups())
            if found < MIN_MISE_VERSION:
                minimum = ".".join(str(part) for part in MIN_MISE_VERSION)
                message = (
                    f"mise {number} is too old; mibare needs mise {minimum} or "
                    "newer. Upgrade with `mise self-update`."
                )
                raise MiseTooOldError(message)
            self._version = number
        return self._version

    def registry(self) -> tuple[RegistryEntry, ...]:
        """Return the registry entries in registry order.

        Returns:
            tuple[RegistryEntry, ...]: The entries from ``mise registry --json``.

        Raises:
            MiseError: If mise is unusable or its output cannot be understood.
        """
        _ = self.version()
        message = "Could not understand the output of `mise registry --json`."
        try:
            parsed = cast("object", json.loads(self._execute("registry", "--json")))
        except ValueError as exc:
            raise MiseError(message) from exc
        if not isinstance(parsed, list):
            raise MiseError(message)
        entries = [_entry(item) for item in cast("list[object]", parsed)]
        if None in entries:
            raise MiseError(message)
        return tuple(entry for entry in entries if entry is not None)

    def recipe_exists(self, backend_string: str) -> bool:
        """Say whether mise can list versions of ``backend_string``.

        Args:
            backend_string: A backend string such as ``aqua:owner/repo``.

        Returns:
            bool: ``True`` when ``mise ls-remote`` exits 0, ``False`` when it
                reports the recipe as not found.

        Raises:
            MiseError: If ``mise ls-remote`` fails for any other reason, so a
                network or rate-limit failure never reads as "absent".
        """
        _ = self.version()
        command, done = self._complete("ls-remote", backend_string)
        if done.returncode == 0:
            return True
        if _ABSENT.search(done.stderr):
            return False
        message = (
            f"`{' '.join(command)}` failed with exit code {done.returncode}: "
            f"{done.stderr.strip()}"
        )
        raise MiseError(message)

    def _execute(self, *arguments: str) -> str:
        """Run `mise` with `arguments`, requiring exit code 0.

        Args:
            *arguments: The arguments to pass to `mise`.

        Returns:
            str: Standard output.

        Raises:
            MiseError: If mise cannot run or exits non-zero.
        """
        command, done = self._complete(*arguments)
        if done.returncode != 0:
            message = (
                f"`{' '.join(command)}` failed with exit code {done.returncode}: "
                f"{done.stderr.strip()}"
            )
            raise MiseError(message)
        return done.stdout

    def _complete(
        self, *arguments: str
    ) -> tuple[tuple[str, ...], subprocess.CompletedProcess[str]]:
        """Run `mise` with `arguments` in an isolated environment.

        Args:
            *arguments: The arguments to pass to `mise`.

        Returns:
            tuple[tuple[str, ...], subprocess.CompletedProcess[str]]: The command
                line and the finished process, whatever its exit code.

        Raises:
            MiseNotFoundError: If there is no `mise` binary.
            MiseError: If mise cannot run.
        """
        with tempfile.TemporaryDirectory(prefix="mibare-") as home:
            env = {"HOME": home, "MISE_NO_CONFIG": "1"}
            env.update({n: os.environ[n] for n in _PASSTHROUGH if n in os.environ})
            command = ("mise", *arguments)
            try:
                done = self._run(command, env, Path(home))
            except FileNotFoundError:
                message = f"mise was not found on PATH. Install it: {_INSTALL_URL}"
                raise MiseNotFoundError(message) from None
            except (OSError, subprocess.TimeoutExpired) as exc:
                message = f"Could not run `{' '.join(command)}`: {exc}"
                raise MiseError(message) from exc
        return command, done
