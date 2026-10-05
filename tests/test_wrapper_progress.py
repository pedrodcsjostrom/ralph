"""The wrapper's indicator looks like ralph's: a runner sees one kind of working indicator.

The wrapper must stay a single standalone file, so it carries its own copy of
ralph's indicator. These tests run both as a runner does, the wrapper fetching
a slow version and ralph waiting on a quiet agent, on a plain output and on a
terminal, and compare the shape of what each writes.
"""

import os
import re
import shutil
import tempfile
import unittest

from tests.harness import ScenarioTestCase
from tests.test_wrapper import WrapperWorld

# What each waits on, as its indicator names it.
FETCH = "fetching ralph v1"
ITERATION = "iteration 1/30, ticket #2, attempt 1/2"

ELAPSED = re.compile(r"\b(\d+h)?(\d+m)?\d+s\b")
ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# What the indicator draws on a terminal: erase the line, then the frame, then back to column 0.
FRAME = re.compile(r"\x1b\[2K([^\r\n\x1b]+)\r")
SPINNERS = {"unicode": set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"), "ascii": set("|/-\\")}


def shape(text, label):
    """text, an indicator's line, with what differs between two indicators taken out: the label, the elapsed time
    and what is happening now."""
    text = ELAPSED.sub("<elapsed>", text.replace(label, "<label>"))
    return re.sub(r"<elapsed>, .+$", "<elapsed>, <activity>", text)


def plain_shapes(output, label):
    return sorted({shape(line, label) for line in output.splitlines() if line.startswith("ralph: working: ")})


def terminal_shape(raw, label):
    """The control sequences the output uses, the spinner it draws, and its frames that name label."""
    frames = [frame for frame in FRAME.findall(raw) if label in frame]
    spinner = {frame[0] for frame in frames}
    alphabet = next((name for name, chars in SPINNERS.items() if spinner <= chars), f"unknown {spinner}")
    shapes = sorted({"<spinner>" + shape(frame[1:], label) for frame in frames})
    return sorted(set(ESCAPE.findall(raw))), alphabet, shapes


class TheWrappersIndicator(ScenarioTestCase):
    def world(self):
        root = tempfile.mkdtemp(prefix="ralph-wrapper-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        w = WrapperWorld(os.path.realpath(root))
        w.release("v1")
        w.pin("v1")
        return w

    def quiet_run(self):
        """A scenario whose only ticket's agent goes quiet for a while in the middle of a tool call."""
        s = self.scenario()
        s.ticket(2)
        s.agent_pauses(1.0)
        return s

    def test_writes_progress_lines_of_the_same_shape_as_ralph_when_output_is_not_a_terminal(self):
        fetch = self.world().wrapper(SLOW_GIT="0.5", RALPH_PROGRESS_INTERVAL="0.2")
        run = self.quiet_run().ralph("run", "1", RALPH_PROGRESS_INTERVAL="0.2")

        self.assertEqual(fetch.status, 0, fetch.output)
        self.assertEqual(run.status, 0, run.output)
        expected = ["ralph: working: <label>, <elapsed>, <activity>"]
        self.assertEqual(plain_shapes(fetch.output, FETCH), expected, fetch.output)
        self.assertEqual([s for s in plain_shapes(run.output, ITERATION) if "<label>" in s], expected, run.output)

    def test_draws_and_erases_its_indicator_on_a_terminal_as_ralph_does(self):
        for encoding, alphabet in (("utf-8", "unicode"), ("ascii", "ascii")):
            with self.subTest(encoding=encoding):
                fetch = self.world().wrapper_on_terminal(SLOW_GIT="0.6", PYTHONIOENCODING=encoding)
                run = self.quiet_run().ralph_on_terminal("run", "1", columns=200, PYTHONIOENCODING=encoding)

                self.assertEqual(fetch.status, 0, fetch)
                self.assertEqual(run.status, 0, run)
                wrapper_shape = terminal_shape(fetch.raw, FETCH)
                self.assertEqual(wrapper_shape, terminal_shape(run.raw, ITERATION))
                self.assertEqual(
                    wrapper_shape,
                    (["\x1b[2K", "\x1b[?25h", "\x1b[?25l"], alphabet, ["<spinner> <label>, <elapsed>, <activity>"]),
                )
                for result, label in ((fetch, FETCH), (run, ITERATION)):
                    self.assertEqual([line for line in result.screen.lines() if label in line], [], result)
                    self.assertTrue(result.screen.cursor_visible, result)

    def test_cuts_its_indicator_to_a_narrow_terminal_as_ralph_does(self):
        columns = 24
        fetch = self.world().wrapper_on_terminal(SLOW_GIT="0.6", columns=columns)
        run = self.quiet_run().ralph_on_terminal("run", "1", columns=columns)

        for result, label in ((fetch, FETCH), (run, ITERATION)):
            self.assertEqual(result.status, 0, result)
            frames = [frame for frame in FRAME.findall(result.raw) if label[: columns // 2] in frame]
            self.assertTrue(frames, result)
            # One cell short of the margin, so the terminal never wraps it.
            self.assertEqual({len(frame) for frame in frames}, {columns - 1}, frames)

    def test_refuses_an_unusable_progress_interval_in_the_same_words_as_ralph(self):
        fetch = self.world().wrapper(RALPH_PROGRESS_INTERVAL="soon")
        run = self.quiet_run().ralph("run", "1", RALPH_PROGRESS_INTERVAL="soon")

        self.assertEqual((fetch.status, run.status), (1, 1))
        self.assertEqual(fetch.output, run.output)
        self.assertEqual(
            fetch.output, "ralph: RALPH_PROGRESS_INTERVAL must be a number of seconds above 0, not 'soon'\n"
        )


if __name__ == "__main__":
    unittest.main()
