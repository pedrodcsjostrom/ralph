"""Config: the settings a run is held to, the verify command and the budgets.

For now they come from environment variables only. The checked-in project
configuration, which these variables will override, arrives later.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from ralph.errors import RalphError


@dataclass(frozen=True)
class Config:
    # A shell command that must pass before a ticket is closed; None skips verification.
    verify: Optional[str] = None
    # Attempts per ticket before it is left alone for the rest of the run.
    max_attempts: int = 2
    # Iterations per run before it stops as not converging.
    max_iterations: int = 30
    # Review rounds per run before it stops as not converging.
    max_review_rounds: int = 3

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        default = cls()
        return cls(
            verify=env.get("RALPH_VERIFY", "").strip() or None,
            max_attempts=_count(env, "RALPH_MAX_ATTEMPTS", default.max_attempts),
            max_iterations=_count(env, "RALPH_MAX_ITERATIONS", default.max_iterations),
            max_review_rounds=_count(env, "RALPH_MAX_REVIEW_ROUNDS", default.max_review_rounds),
        )


def _count(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    if not value.isdigit() or int(value) < 1:
        raise RalphError(f"{name} must be a whole number of at least 1, not {value!r}")
    return int(value)
