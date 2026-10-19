"""Which Go files are built for a target platform.

Go leaves a file out of a build by its name (``_test.go``, ``_windows.go``,
``_linux_amd64.go``) or by a ``//go:build`` line in its header. Both are
evaluated here against a mibare :class:`~mibare.core.platform.Platform`, with
mibare's names mapped to Go's (``macos`` to ``darwin``, ``x64`` to ``amd64``).

Tags are true when they name the target GOOS or GOARCH, are ``unix`` on a Unix
target, are ``gc`` or a ``go1.N`` release tag. Every other tag, such as a
custom build tag or ``cgo``, counts as false. A constraint that does not parse
leaves the file in, since leaving a file out wrongly hides an entrypoint.

Files with legacy ``// +build`` lines and no ``//go:build`` line are filtered by
those too: options separated by spaces are OR, terms separated by commas are
AND, ``!`` negates, and several lines are AND-ed. As in Go, the lines count
only in the header, before a blank line that precedes the package clause. When
both forms exist, ``//go:build`` wins.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mibare.core.platform import Platform

__all__ = ["constraint_matches", "name_matches"]

_KNOWN_OS = frozenset({
    "aix", "android", "darwin", "dragonfly", "freebsd", "hurd", "illumos",
    "ios", "js", "linux", "nacl", "netbsd", "openbsd", "plan9", "solaris",
    "wasip1", "windows", "zos",
})  # fmt: skip
_KNOWN_ARCH = frozenset({
    "386", "amd64", "amd64p32", "arm", "armbe", "arm64", "arm64be", "loong64",
    "mips", "mipsle", "mips64", "mips64le", "mips64p32", "mips64p32le", "ppc",
    "ppc64", "ppc64le", "riscv", "riscv64", "s390", "s390x", "sparc",
    "sparc64", "wasm",
})  # fmt: skip
_UNIX = frozenset({
    "aix", "android", "darwin", "dragonfly", "freebsd", "hurd", "illumos",
    "ios", "linux", "netbsd", "openbsd", "solaris",
})  # fmt: skip
_GO_OS = {"macos": "darwin"}
_GO_ARCH = {"x64": "amd64"}

_BUILD_LINE = re.compile(r"//go:build[ \t]+(.*)")
_PLUS_BUILD_LINE = re.compile(r"//[ \t]*\+build(?:[ \t]+(.*))?")
_PLUS_BUILD_TERM = re.compile(r"!?[\w.]+")
_TOKEN = re.compile(r"\s*(\|\||&&|!|\(|\)|[\w.]+)")
_RELEASE_TAG = re.compile(r"go1\.\d+")


def _go_target(platform: Platform) -> tuple[str, str]:
    """Map ``platform`` to Go's names.

    Returns:
        tuple[str, str]: ``(GOOS, GOARCH)``.
    """
    return _GO_OS.get(platform.os, platform.os), _GO_ARCH.get(
        platform.arch, platform.arch
    )


def name_matches(filename: str, platform: Platform) -> bool:
    """Say whether Go builds a file of this name for ``platform``.

    Args:
        filename: The base name, such as ``main_linux_amd64.go``.
        platform: The target platform.

    Returns:
        bool: ``False`` for ``_test.go`` files, names starting with ``_`` or
            ``.``, and names whose GOOS or GOARCH suffix is another target.
    """
    if filename.startswith(("_", ".")) or filename.endswith("_test.go"):
        return False
    goos, goarch = _go_target(platform)
    parts = filename.removesuffix(".go").split("_")[1:]
    if len(parts) >= 2 and parts[-2] in _KNOWN_OS and parts[-1] in _KNOWN_ARCH:  # noqa: PLR2004
        return parts[-2] == goos and parts[-1] == goarch
    if parts and parts[-1] in _KNOWN_OS:
        return parts[-1] == goos
    if parts and parts[-1] in _KNOWN_ARCH:
        return parts[-1] == goarch
    return True


def _header_comments(source: str) -> Iterator[str]:
    """Yield the line comments that precede the package clause.

    Block comments are skipped; the first line of code ends the header.

    Yields:
        str: Each stripped ``//`` comment line.
    """
    in_block = False
    for raw in source.splitlines():
        line = raw.strip()
        if in_block or line.startswith("/*"):
            in_block = "*/" not in line
        elif line.startswith("//"):
            yield line
        elif line:
            return


def _header_constraint(source: str) -> str | None:
    """Find the ``//go:build`` expression in the header comments.

    Returns:
        str | None: The first expression, or ``None`` when there is none.
    """
    matches = (_BUILD_LINE.fullmatch(line) for line in _header_comments(source))
    return next((m.group(1).strip() for m in matches if m), None)


def _constraint_block(source: str) -> list[str]:
    """Find the header lines Go reads build constraints from.

    That is the run of ``//`` comment lines and blank lines at the top of the
    file, cut after its last blank line: a comment that touches the package
    clause is documentation, not a constraint.

    Returns:
        list[str]: The stripped lines of the run, ending at its last blank line.
    """
    run: list[str] = []
    end = 0
    for raw in source.splitlines():
        line = raw.strip()
        if line and not line.startswith("//"):
            break
        run.append(line)
        if not line:
            end = len(run)
    return run[:end]


def _legacy_constraint(source: str) -> str | None:
    """Turn the ``// +build`` lines of the header into one ``//go:build`` expression.

    Returns:
        str | None: The expression, or ``None`` when there are no such lines.

    Raises:
        ValueError: If a line has no options or an option has a malformed term.
    """
    matches = (_PLUS_BUILD_LINE.fullmatch(line) for line in _constraint_block(source))
    lines = [(match.group(1) or "").split() for match in matches if match]
    if not lines:
        return None
    clauses: list[str] = []
    for options in lines:
        if not options:
            message = "a // +build line has no options"
            raise ValueError(message)
        groups = [option.split(",") for option in options]
        if not all(_PLUS_BUILD_TERM.fullmatch(t) for terms in groups for t in terms):
            message = f"malformed term in // +build line {' '.join(options)!r}"
            raise ValueError(message)
        any_of = " || ".join(f"({' && '.join(terms)})" for terms in groups)
        clauses.append(f"({any_of})")
    return " && ".join(clauses)


def _tokens(expression: str) -> list[str]:
    """Split a constraint into operators and tags.

    Returns:
        list[str]: The tokens.

    Raises:
        ValueError: If the text holds anything else.
    """
    tokens: list[str] = []
    position = 0
    while expression[position:].strip():
        match = _TOKEN.match(expression, position)
        if match is None:
            message = f"unexpected text in build constraint {expression!r}"
            raise ValueError(message)
        tokens.append(match.group(1))
        position = match.end()
    return tokens


@final
class _Evaluator:
    """A recursive-descent evaluator for ``||``, ``&&``, ``!`` and parentheses."""

    def __init__(self, tokens: list[str], platform: Platform) -> None:
        """Evaluate ``tokens`` against ``platform``."""
        self._tokens = tokens
        self._position = 0
        self._goos, self._goarch = _go_target(platform)

    def evaluate(self) -> bool:
        """Evaluate the whole expression.

        Returns:
            bool: The constraint's value.

        Raises:
            ValueError: If the tokens are not one well-formed expression.
        """
        value = self._or()
        if self._position != len(self._tokens):
            message = "unexpected token after the constraint"
            raise ValueError(message)
        return value

    def _peek(self) -> str | None:
        """Look at the next token.

        Returns:
            str | None: The token, or ``None`` at the end.
        """
        if self._position < len(self._tokens):
            return self._tokens[self._position]
        return None

    def _next(self) -> str:
        """Consume the next token.

        Returns:
            str: The token.

        Raises:
            ValueError: If the tokens have run out.
        """
        token = self._peek()
        if token is None:
            message = "the constraint ends early"
            raise ValueError(message)
        self._position += 1
        return token

    def _or(self) -> bool:
        """Evaluate ``and ('||' and)*``.

        Returns:
            bool: The value.
        """
        value = self._and()
        while self._peek() == "||":
            _ = self._next()
            value = self._and() or value
        return value

    def _and(self) -> bool:
        """Evaluate ``not ('&&' not)*``.

        Returns:
            bool: The value.
        """
        value = self._not()
        while self._peek() == "&&":
            _ = self._next()
            value = self._not() and value
        return value

    def _not(self) -> bool:
        """Evaluate ``'!' not`` or an atom.

        Returns:
            bool: The value.
        """
        if self._peek() == "!":
            _ = self._next()
            return not self._not()
        return self._atom()

    def _atom(self) -> bool:
        """Evaluate a parenthesised expression or a tag.

        Returns:
            bool: The value.

        Raises:
            ValueError: If an operator or a closing parenthesis stands where a
                tag should.
        """
        word = self._next()
        if word == "(":
            value = self._or()
            if self._next() != ")":
                message = "missing closing parenthesis"
                raise ValueError(message)
            return value
        if word in {"||", "&&", "!", ")"}:
            message = f"unexpected {word!r}"
            raise ValueError(message)
        return self._tag(word)

    def _tag(self, tag: str) -> bool:
        """Say whether ``tag`` holds for the target.

        Returns:
            bool: ``True`` for the target GOOS or GOARCH, ``unix`` on a Unix
                target, ``gc`` and ``go1.N``; ``False`` for any other tag.
        """
        if tag in {self._goos, self._goarch, "gc"}:
            return True
        if tag == "unix":
            return self._goos in _UNIX
        return _RELEASE_TAG.fullmatch(tag) is not None


def constraint_matches(source: str, platform: Platform) -> bool:
    """Say whether a file's build constraint includes it for ``platform``.

    The ``//go:build`` line decides; a file without one is judged by its legacy
    ``// +build`` lines.

    Args:
        source: The file's text.
        platform: The target platform.

    Returns:
        bool: The constraint's value; ``True`` when the file has none or the
            constraint does not parse.
    """
    try:
        expression = _header_constraint(source) or _legacy_constraint(source)
        if expression is None:
            return True
        return _Evaluator(_tokens(expression), platform).evaluate()
    except ValueError:
        return True
