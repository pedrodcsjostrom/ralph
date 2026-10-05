"""The run directory, where a run keeps its agents' event logs, its record and its pull request draft."""

import os
import re
import time
from typing import Optional

# Relative to the project root. Ignored by git through its own .gitignore, so a
# run never dirties the tree whatever the project's ignore rules say.
RUNS = os.path.join(".ralph", "runs")

# A run directory is named after the second the run started, YYYYmmdd-HHMMSS,
# with -N appended for the Nth run started in that same second.
_NAME = re.compile(r"(\d{8}-\d{6})(?:-(\d+))?")


def create(project_root: str) -> str:
    """Creates a fresh, uniquely named directory for one run and returns its path."""
    runs = os.path.join(project_root, RUNS)
    os.makedirs(runs, exist_ok=True)
    ignore = os.path.join(runs, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w") as f:
            f.write("*\n")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in [""] + [f"-{i}" for i in range(2, 1000)]:
        path = os.path.join(runs, stamp + suffix)
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue
    raise FileExistsError(path)


def _started(name: str) -> tuple[str, int]:
    """When the run named name started, in an order that compares correctly.

    Names alone do not: as text the tenth run of a second, -10, sorts before the second, -2.
    """
    found = _NAME.fullmatch(name)
    assert found is not None
    return found.group(1), int(found.group(2) or 1)


def every(project_root: str) -> list[str]:
    """The directories of the project's runs, in the order they started."""
    runs = os.path.join(project_root, RUNS)
    if not os.path.isdir(runs):
        return []
    names = [n for n in os.listdir(runs) if _NAME.fullmatch(n) and os.path.isdir(os.path.join(runs, n))]
    return [os.path.join(runs, name) for name in sorted(names, key=_started)]


def latest(project_root: str) -> Optional[str]:
    """The directory of the run started last, or None when the project has had no run."""
    found = every(project_root)
    return found[-1] if found else None
