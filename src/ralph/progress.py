"""Progress: the only module that writes the working indicator.

Whoever waits on something says what with `waiting(label)` and may report what
is happening meanwhile through the returned Wait's `doing(activity)`. Waits
nest: an iteration is one wait, the verify command inside it is another, and
the indicator shows the outermost wait, its elapsed time and the innermost
detail:

    iteration 3/30, ticket #4, attempt 1/2, 1m05s, Bash: Run the tests
    iteration 3/30, ticket #4, attempt 1/2, 1m40s, verify: make check (12s)

On a terminal the indicator is one animated line under everything else, redrawn
in place by a thread of its own, so it keeps moving while the waited-on thing
is silent. Everything else written to the same terminal must go through
`above()`, which takes the line away, lets the text scroll up, and puts the line
back underneath. When the stream is not a terminal there is no animation and no
control character: a plain "ralph: working: ..." line is written once every
interval while a wait lasts, so a log shows the run is alive.

The module is self-contained (standard library only, no other ralph module) so
the wrapper can carry a copy of it.
"""

import os
import re
import sys
import threading
import time
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Callable, Optional, TextIO

# Seconds between plain progress lines when output is not a terminal.
INTERVAL = 30.0
# The environment variable that overrides INTERVAL, mostly for tests.
INTERVAL_VARIABLE = "RALPH_PROGRESS_INTERVAL"
# Seconds between frames of the animation on a terminal.
FRAME = 0.1

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_SPINNER = "|/-\\"
# Erases the current line and puts the cursor at its start.
ERASE = "\r\x1b[2K"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
# The longest activity shown, so a plain line stays one readable line.
ACTIVITY_WIDTH = 80

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def interval(env: Mapping[str, str]) -> float:
    """The plain progress interval the environment asks for. Raises ValueError with a message if it is unusable."""
    value = env.get(INTERVAL_VARIABLE, "").strip()
    if not value:
        return INTERVAL
    try:
        seconds = float(value)
    except ValueError:
        seconds = 0.0
    if not seconds > 0 or seconds == float("inf"):
        raise ValueError(f"{INTERVAL_VARIABLE} must be a number of seconds above 0, not {value!r}")
    return seconds


def duration(seconds: float) -> str:
    """A whole-second duration as 7s, 1m05s or 2h03m."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{s % 3600 // 60:02d}m"


def one_line(text: str, width: int = ACTIVITY_WIDTH) -> str:
    """text on one line, free of control characters, cut to width."""
    text = " ".join(_CONTROL.sub(" ", text).split())
    return text if len(text) <= width else text[: width - 3] + "..."


def _cells(char: str) -> int:
    """How many terminal columns char takes."""
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def fit(text: str, columns: int) -> str:
    """text cut to at most columns terminal columns, ending in "..." when it is cut."""
    if sum(_cells(c) for c in text) <= columns:
        return text
    room, kept = max(columns - 3, 0), []
    for char in text:
        room -= _cells(char)
        if room < 0:
            break
        kept.append(char)
    return "".join(kept) + "..."[: max(columns, 0)]


def is_terminal(stream: TextIO, env: Mapping[str, str]) -> bool:
    try:
        return stream.isatty() and env.get("TERM", "") != "dumb"
    except (AttributeError, ValueError):
        return False


class Wait:
    """One thing being waited on."""

    def __init__(self, progress: "Progress", label: str, started: float):
        self._progress = progress
        self.label = label
        self.started = started
        self.activity: Optional[str] = None

    def doing(self, activity: Optional[str]) -> None:
        """What is happening in this wait right now, e.g. the tool an agent uses; None for nothing in particular."""
        self._progress._set_activity(self, activity)


class Progress:
    def __init__(
        self,
        stream: TextIO = sys.stdout,
        interval: float = INTERVAL,
        terminal: Optional[bool] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.stream = stream
        self.interval = interval
        self.terminal = is_terminal(stream, os.environ) if terminal is None else terminal
        self.clock = clock
        self._waits: list[Wait] = []
        self._lock = threading.RLock()
        self._drawn = False
        self._cursor_hidden = False
        self._frame = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        encoding = (getattr(stream, "encoding", None) or "ascii").lower().replace("-", "")
        self._spinner = SPINNER if encoding == "utf8" else ASCII_SPINNER

    @contextmanager
    def waiting(self, label: str) -> Iterator[Wait]:
        """Shows the indicator for label while the block runs, and takes it away when the block ends however it ends."""
        with self._lock:
            wait = Wait(self, one_line(label), self.clock())
            self._waits.append(wait)
            if len(self._waits) == 1:
                self._start()
        try:
            yield wait
        finally:
            thread = None
            with self._lock:
                self._waits.remove(wait)
                if not self._waits:
                    self._stop.set()
                    thread, self._thread = self._thread, None
                    self._erase()
                elif self.terminal:
                    self._draw()
            if thread is not None:
                thread.join()

    @contextmanager
    def above(self) -> Iterator[None]:
        """Lets the block write whole lines to the terminal above the indicator; they never mix with it."""
        with self._lock:
            self._erase(show_cursor=False)
            try:
                yield
            finally:
                if self._waits and self.terminal:
                    self._draw()

    def line(self) -> str:
        """What the indicator says now, without decoration; empty when nothing is waited on."""
        with self._lock:
            if not self._waits:
                return ""
            outer = self._waits[0]
            now = self.clock()
            parts = [outer.label, duration(now - outer.started)]
            inner = self._waits[-1]
            if inner is not outer:
                parts.append(f"{inner.label} ({duration(now - inner.started)})")
            if inner.activity:
                parts.append(inner.activity)
            return ", ".join(parts)

    def _set_activity(self, wait: Wait, activity: Optional[str]) -> None:
        with self._lock:
            wait.activity = one_line(activity) if activity else None
            if self.terminal and wait in self._waits:
                self._draw()

    def _start(self) -> None:
        self._stop = threading.Event()
        self._frame = 0
        self._thread = threading.Thread(target=self._tick, args=(self._stop,), name="ralph-progress", daemon=True)
        self._thread.start()

    def _tick(self, stop: threading.Event) -> None:
        period = FRAME if self.terminal else self.interval
        while not stop.wait(period):
            with self._lock:
                if stop.is_set() or not self._waits:
                    return
                self._frame += 1
                if self.terminal:
                    self._draw()
                else:
                    self._write(f"ralph: working: {self.line()}\n")

    def _draw(self) -> None:
        text = f"{self._spinner[self._frame % len(self._spinner)]} {self.line()}"
        # A line as wide as the terminal or wider would wrap, and redrawing it in place would leave its head behind.
        text = fit(text, self._width() - 1)
        # The cursor is hidden while the indicator is up, and parked at the start of its line, so whatever the
        # terminal echoes (^C when the runner interrupts) lands on the indicator rather than after it, where it
        # could wrap onto a line of its own.
        self._write(("" if self._cursor_hidden else HIDE_CURSOR) + ERASE + text + "\r")
        self._drawn = self._cursor_hidden = True

    def _erase(self, show_cursor: bool = True) -> None:
        """Takes the indicator off the screen, leaving the cursor at the start of its now empty line."""
        text = ""
        if self._drawn:
            text += ERASE
            self._drawn = False
        if show_cursor and self._cursor_hidden:
            text += SHOW_CURSOR
            self._cursor_hidden = False
        if text:
            self._write(text)

    def _width(self) -> int:
        try:
            columns = os.get_terminal_size(self.stream.fileno()).columns
        except (AttributeError, ValueError, OSError):
            columns = 0
        return columns or 80

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()
