"""What the runner reads on the terminal: ralph's own messages and the agents' prose."""

import sys
from typing import Optional, TextIO

from ralph.progress import Progress


class Console:
    def __init__(self, out: TextIO = sys.stdout, err: TextIO = sys.stderr, progress: Optional[Progress] = None):
        self.out = out
        self.err = err
        # The working indicator lives under everything written here.
        self.progress = progress or Progress(out)

    def _write(self, stream: TextIO, text: str) -> None:
        with self.progress.above():
            stream.write(text)
            stream.flush()

    def say(self, message: str) -> None:
        self._write(self.out, f"ralph: {message}\n")

    def heading(self, title: str) -> None:
        self._write(self.out, f"\n=== {title} ===\n")

    def prose(self, text: str) -> None:
        """A piece of an agent's prose, as it streams."""
        self._write(self.out, text.rstrip("\n") + "\n\n")

    def document(self, text: str) -> None:
        """A whole document, such as the help, as it is."""
        self._write(self.out, text)

    def error(self, message: str) -> None:
        self.out.flush()
        self._write(self.err, f"ralph: {message}\n")

    def passthrough(self, text: str) -> None:
        """Output of a tool ralph runs that is meant for the runner, such as an agent's warnings."""
        self._write(self.err, text if text.endswith("\n") else text + "\n")
