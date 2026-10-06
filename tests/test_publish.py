"""The publish command: the one deliberate step that pushes the integration branch and opens the pull request."""

import os
import re
import unittest

from tests.harness import SPEC_TITLE, ScenarioTestCase

BRANCH = "spec/1-spec-widget-sorting"


def draft_of(run):
    with open(os.path.join(run, "pull-request.md")) as f:
        return f.read()


class AfterACleanRun(ScenarioTestCase):
    def test_pushes_the_integration_branch_and_opens_a_pull_request_against_main_with_the_draft_as_its_body(self):
        s = self.scenario()
        s.add_remote()
        s.ticket(2)
        self.assertEqual(s.ralph("run", "1").status, 0)
        [run] = s.run_dirs()

        result = s.ralph("publish")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.remote_branches(), {BRANCH: s.git("rev-parse", BRANCH)})
        [pull] = s.pull_requests()
        self.assertEqual(
            pull,
            {"number": pull["number"], "base": "main", "head": BRANCH, "title": SPEC_TITLE, "body": draft_of(run)},
        )
        self.assertIn(f"https://github.com/acme/widgets/pull/{pull['number']}", result.output)


def unclean_run(s):
    """A run that stops with ticket #2 still open, having given up on it."""
    s.ticket(2)
    s.agent_does(2, "blocked")
    result = s.ralph("run", "1", RALPH_MAX_ATTEMPTS="1")
    assert result.status == 1, result.output


class AfterAnUncleanRun(ScenarioTestCase):
    def test_refuses_saying_why_and_pushes_nothing(self):
        s = self.scenario()
        s.add_remote()
        unclean_run(s)
        [run] = s.run_dirs()

        result = s.ralph("publish")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(
            result.output,
            f"ralph: the latest run, {run}, did not end cleanly, so it is not published:\n"
            "  stopping, these tickets are open and nothing on the frontier can be implemented:\n"
            "  #2 Ticket 2\n"
            "rerun to finish the spec, or publish it as it is with `ralph publish --force`\n",
        )
        self.assertEqual(s.remote_branches(), {})
        self.assertEqual(s.pull_requests(), [])

    def test_publishes_it_anyway_with_force(self):
        s = self.scenario()
        s.add_remote()
        unclean_run(s)
        [run] = s.run_dirs()

        result = s.ralph("publish", "--force")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.remote_branches(), {BRANCH: s.git("rev-parse", BRANCH)})
        [pull] = s.pull_requests()
        self.assertEqual((pull["head"], pull["body"]), (BRANCH, draft_of(run)))
        self.assertIn("Stopped before it could end cleanly", pull["body"])


class TheLatestRun(ScenarioTestCase):
    def test_is_the_one_started_last_even_when_ten_runs_started_in_the_same_second(self):
        s = self.scenario()
        s.add_remote()
        unclean_run(s)
        s.agent_does(2, "complete")
        self.assertEqual(s.ralph("run", "1").status, 0)
        first, second = s.run_dirs()
        # As text, the tenth run of a second, -10, sorts before the second, -2.
        runs = os.path.dirname(first)
        os.rename(first, os.path.join(runs, "20261005-120000-2"))
        os.rename(second, os.path.join(runs, "20261005-120000-10"))

        result = s.ralph("publish")

        self.assertEqual(result.status, 0, result.output)
        [pull] = s.pull_requests()
        self.assertEqual(pull["body"], draft_of(os.path.join(runs, "20261005-120000-10")))


class ARun(ScenarioTestCase):
    def test_never_pushes(self):
        s = self.scenario()
        s.add_remote()
        s.ticket(2)
        s.ticket(3)
        s.review_finds(1, {"title": "Fix", "what_to_build": "Fix it.", "acceptance_criteria": ["Fixed"]})

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.remote_branches(), {})
        self.assertEqual(s.pull_requests(), [])


class WithoutADraft(ScenarioTestCase):
    def test_a_run_without_a_draft_fails_saying_so_and_pushes_nothing(self):
        s = self.scenario()
        s.add_remote()
        s.ticket(2)
        self.assertEqual(s.ralph("run", "1").status, 0)
        [run] = s.run_dirs()
        os.remove(os.path.join(run, "pull-request.md"))

        result = s.ralph("publish")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(
            result.output,
            f"ralph: the latest run, {run}, left no pull request draft to publish ({run}/pull-request.md is missing)\n",
        )
        self.assertEqual(s.remote_branches(), {})
        self.assertEqual(s.pull_requests(), [])

    def test_a_project_that_has_had_no_run_fails_saying_so(self):
        s = self.scenario()
        s.add_remote()

        result = s.ralph("publish")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(
            result.output, "ralph: there is no run to publish in this project; start one with `ralph run <spec>`\n"
        )
        self.assertEqual(s.pull_requests(), [])


def published_run(s):
    """A clean run, ready to publish to a remote."""
    s.add_remote()
    s.ticket(2)
    assert s.ralph("run", "1").status == 0


class WhileWaiting(ScenarioTestCase):
    def test_pushing_writes_plain_progress_lines(self):
        s = self.scenario()
        published_run(s)
        s.remote_delays(0.6)

        result = s.ralph("publish", RALPH_PROGRESS_INTERVAL="0.2")

        self.assertEqual(result.status, 0, result.output)
        self.assertIn(f"ralph: working: pushing {BRANCH}, 0s\n", result.output)
        self.assertIsNone(re.search(r"[\x00-\x08\x0b-\x1f\x7f]", result.output), repr(result.output))

    def test_opening_the_pull_request_writes_plain_progress_lines(self):
        s = self.scenario()
        published_run(s)
        s.tracker_delays(0.6, only="pr create")

        result = s.ralph("publish", RALPH_PROGRESS_INTERVAL="0.2")

        self.assertEqual(result.status, 0, result.output)
        self.assertIn(f"ralph: working: GitHub: opening a pull request of {BRANCH}, 0s\n", result.output)


class InterruptedOnATerminal(ScenarioTestCase):
    def assertNothingLeftBehind(self, result, label):
        self.assertIn("\x1b[?25l", result.raw, "the indicator was never drawn")
        self.assertIn(label, result.raw, "the indicator was never drawn")
        self.assertEqual([line for line in result.screen.lines() if label in line], [], result)
        self.assertIn("ralph: interrupted", result.screen.lines(), result)
        self.assertTrue(result.screen.cursor_visible, result)

    def test_while_pushing_leaves_the_terminal_usable(self):
        s = self.scenario()
        published_run(s)
        s.remote_delays(30)

        result = s.ralph_on_terminal("publish", interrupt_when=f"pushing {BRANCH}")

        self.assertEqual(result.status, 130, result)
        self.assertNothingLeftBehind(result, "pushing ")
        self.assertEqual(s.pull_requests(), [])

    def test_while_opening_the_pull_request_leaves_the_terminal_usable(self):
        s = self.scenario()
        published_run(s)
        s.tracker_delays(30, only="pr create")

        result = s.ralph_on_terminal("publish", columns=200, interrupt_when="GitHub: opening a pull request")

        self.assertEqual(result.status, 130, result)
        self.assertIn(f"ralph: pushed {BRANCH}", result.screen.lines())
        self.assertNothingLeftBehind(result, "GitHub: ")


if __name__ == "__main__":
    unittest.main()
