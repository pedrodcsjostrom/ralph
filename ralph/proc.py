"""Running the external tools ralph drives. Used by Tracker, Agent and Checkout only."""

import shutil
import subprocess
from typing import Optional, Sequence

from ralph.errors import RalphError


def on_path(tool: str) -> bool:
    return shutil.which(tool) is not None


def succeeds(args: Sequence[str], cwd: Optional[str] = None) -> bool:
    try:
        proc = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return proc.returncode == 0


def output(args: Sequence[str], cwd: Optional[str] = None) -> str:
    """The command's standard output. A failure stops the run with its error output."""
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError as e:
        raise RalphError("could not run %s: %s" % (args[0], e))
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "exit status %d" % proc.returncode
        raise RalphError("`%s` failed: %s" % (" ".join(args[:3]), detail))
    return proc.stdout
