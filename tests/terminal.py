"""Running a command on a pseudo-terminal, and what a runner would then see on the screen.

`run(argv, cwd, env)` starts the command as the foreground job of a fresh
pseudo-terminal, the way a shell would, and returns everything it wrote. Given
`interrupt_when`, it types Ctrl-C once that text has appeared.

`Screen` replays that output the way a terminal would: it knows printable
text, carriage return, line feed, wrapping at the right margin, erasing a line
and showing or hiding the cursor. Any other control sequence fails the replay,
so a new kind of output gets a deliberate look before it is accepted.
"""

import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time

COLUMNS = 60
ROWS = 24

_SEQUENCE = re.compile(r"\x1b\[(\??)([0-9;]*)([A-Za-z])|([\r\n])|([\x00-\x1f\x7f])|([^\x00-\x1f\x7f]+)")


class TerminalResult:
    def __init__(self, status, raw, columns):
        self.status = status
        self.raw = raw
        self.screen = Screen(columns)
        self.screen.feed(raw)

    def __repr__(self):
        return f"TerminalResult(status={self.status!r}, screen={self.screen.lines()!r}, raw={self.raw!r})"


class Screen:
    def __init__(self, columns=COLUMNS):
        self.columns = columns
        self.rows = [[]]
        self.row = 0
        self.column = 0
        self.cursor_visible = True

    def feed(self, text):
        for match in _SEQUENCE.finditer(text):
            private, params, final, newline, control, printable = match.groups()
            if printable:
                for char in printable:
                    self._put(char)
            elif newline == "\r":
                self.column = 0
            elif newline == "\n":
                self.row += 1
                while len(self.rows) <= self.row:
                    self.rows.append([])
            elif final == "K" and not private and params in ("", "0"):
                del self.rows[self.row][self.column :]
            elif final == "K" and not private and params == "2":
                self.rows[self.row] = [" "] * self.column
            elif final in "lh" and private and params == "25":
                self.cursor_visible = final == "h"
            elif control == "\x07":
                pass
            else:
                raise AssertionError(f"the screen does not know {match.group(0)!r}")

    def _put(self, char):
        if self.column >= self.columns:
            # The line is full: the terminal wraps onto the next one.
            self.row += 1
            self.column = 0
            while len(self.rows) <= self.row:
                self.rows.append([])
        line = self.rows[self.row]
        while len(line) < self.column:
            line.append(" ")
        if self.column < len(line):
            line[self.column] = char
        else:
            line.append(char)
        self.column += 1

    def lines(self):
        """Every line the runner can see, top to bottom, without trailing blanks."""
        return ["".join(row).rstrip() for row in self.rows]


def run(argv, cwd, env, columns=COLUMNS, interrupt_when=None, timeout=60):
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.chdir(cwd)
            os.execve(argv[0], argv, env)
        finally:
            os._exit(127)

    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, columns, 0, 0))
    output = b""
    interrupted = interrupt_when is None
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError as e:
                    if e.errno != errno.EIO:
                        raise
                    chunk = b""
                if not chunk:
                    break
                output += chunk
            if not interrupted and interrupt_when.encode() in output:
                # Ctrl-C, typed by the runner: the terminal signals the whole foreground job.
                os.write(master, b"\x03")
                interrupted = True
        else:
            os.kill(pid, signal.SIGKILL)
            raise AssertionError(f"still running after {timeout}s: {output!r}")
    finally:
        os.close(master)
    _, status = os.waitpid(pid, 0)
    return TerminalResult(os.waitstatus_to_exitcode(status), output.decode("utf-8", "replace"), columns)
