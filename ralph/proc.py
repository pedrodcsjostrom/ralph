"""Running the external tools ralph drives. Used by Tracker, Agent and Checkout only."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Optional

from ralph.errors import RalphError


def on_path(tool: str) -> bool:
    return shutil.which(tool) is not None


def succeeds(args: Sequence[str], cwd: Optional[str] = None) -> bool:
    try:
        proc = subprocess.run(
            args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError:
        return False
    return proc.returncode == 0


def completed(
    args: Sequence[str], cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None
) -> subprocess.CompletedProcess:
    """The finished command with its captured output, whatever its exit status."""
    try:
        return subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    except OSError as e:
        raise RalphError(f"could not run {args[0]}: {e}") from e


def output(args: Sequence[str], cwd: Optional[str] = None) -> str:
    """The command's standard output. A failure stops the run with its error output."""
    proc = completed(args, cwd=cwd)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit status {proc.returncode}"
        raise RalphError(f"`{' '.join(args[:3])}` failed: {detail}")
    return proc.stdout
