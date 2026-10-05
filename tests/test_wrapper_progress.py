"""The wrapper's indicator is a copy of src/ralph/progress.py, since the wrapper cannot import ralph.

These keep the copy in step: driven the same way, both write the same bytes.
"""

import io
import os
import time
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from unittest import mock

from ralph import progress

WRAPPER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wrapper", "ralph")
_loader = SourceFileLoader("ralph_wrapper", WRAPPER)
wrapper = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(wrapper)


class Stream(io.StringIO):
    def __init__(self, encoding="utf-8"):
        super().__init__()
        self._encoding = encoding

    @property
    def encoding(self):
        return self._encoding


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def drive(module, stream, terminal, clock, interval=1000.0):
    """One fetch-like wait: two steps, the second after a while, then the end of the wait."""
    p = module.Progress(stream, interval, terminal=terminal, clock=clock)
    with p.waiting("fetching ralph v1") as wait:
        wait.doing("git ls-remote")
        clock.now += 65
        wait.doing("git\tfetch\n" + "x" * 100)
        line = p.line()
    return line, stream.getvalue()


class TheWrappersIndicator(unittest.TestCase):
    def test_draws_and_erases_on_a_terminal_exactly_as_ralph_does(self):
        for encoding in ("utf-8", "ascii"):
            with self.subTest(encoding=encoding):
                outputs = []
                for module in (progress, wrapper):
                    with mock.patch.object(module, "FRAME", 1000.0):
                        outputs.append(drive(module, Stream(encoding), True, Clock()))
                self.assertEqual(outputs[1], outputs[0])
                self.assertIn("\x1b[?25l", outputs[0][1])

    def test_writes_the_same_plain_lines_as_ralph_when_output_is_not_a_terminal(self):
        outputs = []
        for module in (progress, wrapper):
            stream, clock = Stream(), Clock()
            p = module.Progress(stream, 0.05, terminal=False, clock=clock)
            with p.waiting("fetching ralph v1") as wait:
                wait.doing("git fetch")
                clock.now += 7
                deadline = time.monotonic() + 5
                while "\n" not in stream.getvalue() and time.monotonic() < deadline:
                    time.sleep(0.01)
            outputs.append(stream.getvalue().splitlines()[0])
        self.assertEqual(outputs[1], outputs[0])
        self.assertEqual(outputs[0], "ralph: working: fetching ralph v1, 7s, git fetch")

    def test_shares_ralphs_timings_and_text_helpers(self):
        for name in ("INTERVAL", "INTERVAL_VARIABLE", "FRAME", "SPINNER", "ASCII_SPINNER", "ERASE", "ACTIVITY_WIDTH"):
            self.assertEqual(getattr(wrapper, name), getattr(progress, name), name)
        for seconds in (0, 7.9, 65, 3600 * 2 + 180):
            self.assertEqual(wrapper.duration(seconds), progress.duration(seconds))
        for text, columns in (("short", 10), ("a longer line than fits", 10), ("中文字符", 5), ("", 2)):
            self.assertEqual(wrapper.fit(text, columns), progress.fit(text, columns))
        self.assertEqual(wrapper.one_line("a\x1b[2K\nb " + "c" * 90), progress.one_line("a\x1b[2K\nb " + "c" * 90))

    def test_reads_the_interval_as_ralph_does(self):
        for value in ("", "0.5", " 2 "):
            env = {"RALPH_PROGRESS_INTERVAL": value}
            self.assertEqual(wrapper.interval(env), progress.interval(env))
        for value in ("soon", "0", "-1", "inf", "nan"):
            env = {"RALPH_PROGRESS_INTERVAL": value}
            with self.assertRaises(ValueError) as expected:
                progress.interval(env)
            with self.assertRaises(wrapper.Failure) as got:
                wrapper.interval(env)
            self.assertEqual(str(got.exception), str(expected.exception))


if __name__ == "__main__":
    unittest.main()
