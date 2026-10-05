"""Project: where the project is, and the project rules it checks in.

The project is the directory the wrapper lives in; the wrapper passes it in
RALPH_PROJECT, so a command acts on that project wherever it is run from. Run
without the wrapper, the project is the git repository holding the current
directory. Its ralph directory, `.ralph`, holds the pin, the configuration
(see ralph.config) and the project rules.
"""

import os
from collections.abc import Mapping

from ralph.checkout import Checkout

# The project rules files, one per kind of iteration, appended to ralph's own instructions.
RULES = {
    "implement": os.path.join(".ralph", "rules", "implement.md"),
    "review": os.path.join(".ralph", "rules", "review.md"),
}


def root(env: Mapping[str, str]) -> str:
    """The project's root: the root of the repository holding RALPH_PROJECT, else the current directory."""
    return Checkout.at(env.get("RALPH_PROJECT") or os.getcwd()).root


def rules(project: str, kind: str) -> str:
    """The project rules for one kind of iteration, "implement" or "review"; empty when there are none."""
    try:
        with open(os.path.join(project, RULES[kind]), encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
