"""Config: the settings a run is held to, from the project's configuration file and the environment.

The configuration file is `.ralph/config` at the project root, checked in so
every runner uses the same settings. It holds one `key = value` per line;
blank lines and lines starting with `#` are ignored. Each key can be
overridden for one run by its environment variable, RALPH_ followed by the key
in capitals. An empty value, in the file or the environment, means the
default. An unknown key or a malformed value stops the run before it starts.
"""

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Optional

from ralph.errors import RalphError

FILE = os.path.join(".ralph", "config")


@dataclass(frozen=True)
class Key:
    name: str
    default: str
    meaning: str
    parse: Callable[[str], object]

    @property
    def env(self) -> str:
        return "RALPH_" + self.name.upper()


class Malformed(ValueError):
    pass


def _text(value: str) -> str:
    return value


def _count(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise Malformed("must be a whole number of at least 1")
    return int(value)


def _flags(value: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(value))
    except ValueError as e:
        raise Malformed(f"must be flags as a shell would split them ({e})") from None


KEYS = (
    Key("verify", "", "shell command that must pass before a ticket is closed; empty skips verification", _text),
    Key("main_branch", "main", "the branch a run never commits to and takes its run base from", _text),
    Key(
        "run_base",
        "",
        "the commit the first review compares against; empty means the merge base with main_branch",
        _text,
    ),
    Key("max_attempts", "2", "attempts per ticket before it is left alone for the rest of the run", _count),
    Key("max_review_rounds", "3", "review rounds per run before it stops as not converging", _count),
    Key(
        "max_iterations",
        "30",
        "iterations per run, implementing or reviewing, before it stops as not converging",
        _count,
    ),
    Key("agent_flags", "", "extra flags for every Claude Code launch, split as a shell would", _flags),
)
_BY_NAME = {key.name: key for key in KEYS}


@dataclass(frozen=True)
class Config:
    # A shell command that must pass before a ticket is closed; None skips verification.
    verify: Optional[str] = None
    # The branch a run never commits to and takes its run base from.
    main_branch: str = "main"
    # The commit the run's first review compares against; None means the merge base with main_branch.
    run_base: Optional[str] = None
    # Attempts per ticket before it is left alone for the rest of the run.
    max_attempts: int = 2
    # Review rounds per run before it stops as not converging.
    max_review_rounds: int = 3
    # Iterations per run before it stops as not converging.
    max_iterations: int = 30
    # Extra flags for every Claude Code launch.
    agent_flags: tuple[str, ...] = ()

    @classmethod
    def load(cls, project: str, env: Mapping[str, str]) -> "Config":
        """The project's configuration with the environment's overrides. Raises RalphError naming every problem."""
        problems: list[str] = []
        raw = _read(os.path.join(project, FILE), problems)
        values: dict[str, object] = {}
        for key in KEYS:
            if key.env in env:
                value, source = env[key.env].strip(), key.env
            else:
                value, source = raw.get(key.name, ""), f"{FILE}: {key.name}"
            value = value or key.default
            try:
                values[key.name] = key.parse(value)
            except Malformed as e:
                problems.append(f"{source} {e}, not {value!r}")
        if problems:
            if len(problems) == 1:
                raise RalphError(problems[0])
            raise RalphError("cannot start:\n" + "\n".join("  - " + p for p in problems))
        return cls(
            verify=values["verify"] or None,
            main_branch=values["main_branch"],
            run_base=values["run_base"] or None,
            max_attempts=values["max_attempts"],
            max_review_rounds=values["max_review_rounds"],
            max_iterations=values["max_iterations"],
            agent_flags=values["agent_flags"],
        )


def _read(path: str, problems: list[str]) -> dict[str, str]:
    """The file's keys and values, adding a problem for every line that is not one known key's setting."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return {}
    raw: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, equals, value = line.partition("=")
        name = name.strip()
        if not equals or not name:
            problems.append(f"{FILE} line {number} is not `key = value`: {line!r}")
        elif name not in _BY_NAME:
            problems.append(f"{FILE}: unknown key {name!r} on line {number}; the keys are {', '.join(_BY_NAME)}")
        elif name in raw:
            problems.append(f"{FILE}: {name} is set twice, the second time on line {number}")
        else:
            raw[name] = value.strip()
    return raw
