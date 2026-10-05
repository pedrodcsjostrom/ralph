"""The run directory, where a run keeps its agents' event logs."""

import os
import time

# Relative to the project root. Ignored by git through its own .gitignore, so a
# run never dirties the tree whatever the project's ignore rules say.
RUNS = os.path.join(".ralph", "runs")


def create(project_root: str) -> str:
    """Creates a fresh, uniquely named directory for one run and returns its path."""
    runs = os.path.join(project_root, RUNS)
    os.makedirs(runs, exist_ok=True)
    ignore = os.path.join(runs, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w") as f:
            f.write("*\n")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in [""] + ["-%d" % i for i in range(2, 1000)]:
        path = os.path.join(runs, stamp + suffix)
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue
    raise FileExistsError(path)
