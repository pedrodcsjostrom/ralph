"""Verify: runs the project's verify command, which must pass before a ticket is closed."""

import subprocess
from dataclasses import dataclass
from typing import Optional

from ralph.errors import RalphError

# How much of a failure's output goes on the ticket for the next attempt.
TAIL_LINES = 40


@dataclass(frozen=True)
class Failure:
    command: str
    status: int
    output: str

    def tail(self, lines: int = TAIL_LINES) -> str:
        return "\n".join(self.output.rstrip("\n").splitlines()[-lines:])


def run(command: str, cwd: str) -> Optional[Failure]:
    """Runs command with /bin/sh at cwd. None when it passes, else what went wrong."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except OSError as e:
        raise RalphError(f"could not run the verify command `{command}`: {e}") from e
    if proc.returncode == 0:
        return None
    return Failure(command, proc.returncode, proc.stdout)
