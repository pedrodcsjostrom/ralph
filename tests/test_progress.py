"""The working indicator: a runner can tell a quiet run from a hung one."""

import re
import shutil
import unittest

from tests.harness import ScenarioTestCase

# Anything a log file should never hold: escape sequences, carriage returns and other control characters.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def progress_lines(output):
    return [line for line in output.splitlines() if line.startswith("ralph: working: ")]


class PlainProgress(ScenarioTestCase):
    def test_a_quiet_iteration_writes_plain_progress_lines_naming_where_the_run_is_and_what_the_agent_does(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_pauses(1.0)

        result = s.ralph("run", "1", RALPH_PROGRESS_INTERVAL="0.2")

        self.assertEqual(result.status, 0, result.output)
        lines = progress_lines(result.output)
        self.assertGreaterEqual(len(lines), 3, result.output)
        self.assertRegex(
            lines[-1], r"^ralph: working: iteration 1/30, ticket #2, attempt 1/2, \ds, Bash: Run the tests$"
        )
        self.assertIsNone(CONTROL.search(result.output), repr(result.output))

    def test_waiting_on_the_verify_command_writes_progress_within_the_iteration(self):
        s = self.scenario()
        s.ticket(2)
        s.install_tool("sleep", shutil.which("sleep"))

        result = s.ralph("run", "1", RALPH_VERIFY="sleep 1", RALPH_PROGRESS_INTERVAL="0.2")

        self.assertEqual(result.status, 0, result.output)
        self.assertRegex(
            result.output,
            r"(?m)^ralph: working: iteration 1/30, ticket #2, attempt 1/2, \ds, verify: sleep 1 \(\ds\)$",
        )

    def test_waiting_on_the_tracker_writes_progress(self):
        s = self.scenario()
        s.ticket(2)
        s.tracker_delays(0.5)

        result = s.ralph("run", "1", RALPH_PROGRESS_INTERVAL="0.2")

        self.assertEqual(result.status, 0, result.output)
        lines = progress_lines(result.output)
        self.assertIn("ralph: working: GitHub: reading the tickets of #1, 0s", lines)
        self.assertIn("ralph: working: GitHub: closing #2, 0s", lines)

    def test_an_unusable_interval_is_refused(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1", RALPH_PROGRESS_INTERVAL="soon")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: RALPH_PROGRESS_INTERVAL must be a number of seconds above 0, not 'soon'", result.output)
        self.assertEqual(s.events(), [])

    def test_a_quick_wait_writes_no_progress(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(progress_lines(result.output), [])


# What only the indicator writes: its spinner and how it names an iteration.
INDICATOR = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]|iteration \d+/\d+|GitHub: ")


class TerminalIndicator(ScenarioTestCase):
    def assertNothingLeftBehind(self, result):
        self.assertIn("\x1b[?25l", result.raw, "the indicator was never drawn")
        self.assertIn("iteration 1/30, ticket #2, attempt 1/2", result.raw, "the indicator was never drawn")
        left = [line for line in result.screen.lines() if INDICATOR.search(line)]
        self.assertEqual(left, [], result)
        self.assertTrue(result.screen.cursor_visible, result)

    def test_prose_scrolls_above_the_indicator_and_nothing_of_it_is_left_after_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_pauses(0.6)

        result = s.ralph_on_terminal("run", "1", columns=200)

        self.assertEqual(result.status, 0, result)
        lines = result.screen.lines()
        self.assertIn("Working on ticket #2.", lines)
        self.assertIn("Fake agent finished ticket #2. <promise>TICKET COMPLETE</promise>", lines)
        self.assertIn("ralph: closed #2", lines)
        self.assertEqual(lines[-2:], ["ralph: nothing was pushed. Look it over, then open the pull request.", ""])
        self.assertNothingLeftBehind(result)

    def test_an_interrupt_takes_the_indicator_away_and_leaves_the_cursor_visible(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_pauses(30)

        # On a narrow terminal the indicator must be cut short: one that wraps leaves its head behind when redrawn.
        result = s.ralph_on_terminal("run", "1", columns=60, interrupt_when="Bash: Run")

        self.assertEqual(result.status, 130, result)
        lines = result.screen.lines()
        self.assertIn("Working on ticket #2.", lines)
        self.assertEqual(lines[-2:], ["ralph: interrupted", ""])
        self.assertNothingLeftBehind(result)


if __name__ == "__main__":
    unittest.main()
