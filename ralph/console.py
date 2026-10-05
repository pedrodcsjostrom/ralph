"""What the runner reads on the terminal: ralph's own messages and the agents' prose."""

import sys
from typing import TextIO


class Console:
    def __init__(self, out: TextIO = sys.stdout, err: TextIO = sys.stderr):
        self.out = out
        self.err = err

    def _write(self, stream: TextIO, text: str) -> None:
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
