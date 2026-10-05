"""The pin: the ralph version a project runs, and moving it to another release.

A release is a tag on the public ralph repository and the pin is that tag's
name, one line in `.ralph/pin` at the project root. The wrapper reads the pin;
this module only reads it to report the change and writes it on an upgrade.
"""

import os
import re
from typing import Optional

from ralph import checkout
from ralph.errors import RalphError

PIN = os.path.join(".ralph", "pin")
# Where releases come from; RALPH_REPOSITORY overrides it, as it does for the wrapper.
REPOSITORY = "https://github.com/pedrodcsjostrom/ralph"
# A tag name that is also safe as a single directory name in the wrapper's cache.
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def repository() -> str:
    return os.environ.get("RALPH_REPOSITORY") or REPOSITORY


def read(project: str) -> str:
    try:
        with open(os.path.join(project, PIN)) as f:
            return f.read().strip()
    except FileNotFoundError:
        raise RalphError(f"no pin at {PIN}; this project is not set up to run ralph") from None


def write(project: str, version: str) -> None:
    with open(os.path.join(project, PIN), "w") as f:
        f.write(version + "\n")


def newest(versions: list[str]) -> str:
    """The highest version, comparing runs of digits as numbers: v0.10.0 is newer than v0.9.0."""
    return max(versions, key=_version_order)


def _version_order(version: str) -> list[tuple[int, int, str]]:
    return [(1, int(part), "") if part.isdigit() else (0, 0, part) for part in re.findall(r"\d+|\D+", version)]


def upgrade(project: str, version: Optional[str] = None) -> tuple[str, str]:
    """Moves the project's pin to version, or to the newest release when there is none.

    Gives the versions moved from and to.
    """
    current = read(project)
    source = repository()
    releases = [tag for tag in checkout.remote_tags(source) if VERSION.match(tag)]
    if version is not None:
        if version not in releases:
            raise RalphError(f"there is no version {version} in {source}; the pin stays at {current}")
        target = version
    elif releases:
        target = newest(releases)
    else:
        raise RalphError(f"there are no released versions in {source}")
    if target != current:
        write(project, target)
    return current, target
