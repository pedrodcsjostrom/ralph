"""The pull request draft: every run, clean or not, leaves one in its run directory, assembled from what it recorded."""

import os
import unittest

from tests.harness import ScenarioTestCase


def finding(title):
    return {"title": title, "what_to_build": "Equal widgets keep their order.", "acceptance_criteria": ["Stable"]}


def read_draft(s):
    [run] = s.run_dirs()
    with open(os.path.join(run, "pull-request.md")) as f:
        return f.read()


def short_shas(s, revisions):
    """The 9-character shas of the commits in revisions, oldest first."""
    return [sha[:9] for sha in s.git("log", "--reverse", "--format=%H", revisions).splitlines()]


class ACleanRun(ScenarioTestCase):
    def test_lists_each_ticket_with_its_commits_each_review_round_with_its_fix_tickets_and_a_clean_ending(self):
        s = self.scenario()
        s.ticket(2, title="Sort widgets")
        s.ticket(3, title="Sort by colour", blocked_by=[2])
        s.agent_does(3, "blocked", "complete")
        s.review_finds(1, finding("Sort is unstable"))

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        two, three, fix = short_shas(s, "main..HEAD")
        base = s.git("rev-parse", "--short=9", "main")
        self.assertEqual(
            read_draft(s),
            f"Implements spec #1 on `spec/1-spec-widget-sorting`, from base `{base}`.\n"
            "\n"
            "## How the run ended\n"
            "\n"
            "Ended cleanly: every ticket is closed and nothing is left unreviewed.\n"
            "\n"
            "## Tickets\n"
            "\n"
            "- #2 Sort widgets: closed after 1 attempt\n"
            f"  - `{two}` Implement ticket (#2)\n"
            "- #3 Sort by colour: closed after 2 attempts\n"
            f"  - `{three}` Implement ticket (#3)\n"
            "- #4 Sort is unstable, a fix ticket from review round 1: closed after 1 attempt\n"
            f"  - `{fix}` Implement ticket (#4)\n"
            "\n"
            "## Review rounds\n"
            "\n"
            f"- Round 1, since `{base}`: fix tickets #4\n"
            f"- Round 2, since `{three}`, the fixes for #4: found nothing\n",
        )
        self.assertEqual([s.issue(n)["state"] for n in (2, 3, 4)], ["closed"] * 3)
        self.assertEqual(s.issue(4)["title"], "Sort is unstable")
        self.assertEqual(
            s.log("main..HEAD"), ["Implement ticket (#2)", "Implement ticket (#3)", "Implement ticket (#4)"]
        )

    def test_the_final_message_points_at_the_draft(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        [run] = s.run_dirs()
        self.assertTrue(
            result.output.endswith(f"the pull request draft is {run}/pull-request.md\n"), result.output.splitlines()[-1]
        )


class AStoppedRun(ScenarioTestCase):
    def test_still_writes_a_draft_that_says_how_it_ended_and_points_at_it(self):
        def exhausted_ticket(s):
            s.agent_does(2, "blocked")
            return {"RALPH_MAX_ATTEMPTS": "1"}, "stopping, these tickets are open and nothing on the frontier"

        def iteration_budget(s):
            s.ticket(3)
            return {"RALPH_MAX_ITERATIONS": "1"}, "the iteration budget (1) is spent with work left"

        def review_budget(s):
            s.review_finds(1, finding("More"))
            return {"RALPH_MAX_REVIEW_ROUNDS": "1"}, "the review round budget (1) is spent"

        def dirty_tree(s):
            s.agent_does(2, "dirty")
            return {}, "iteration 1 (ticket #2) left uncommitted changes"

        def malformed_review(s):
            s.review_writes(1, "Found two problems")
            return {}, "review round 1 wrote findings to"

        for case in (exhausted_ticket, iteration_budget, review_budget, dirty_tree, malformed_review):
            with self.subTest(case.__name__):
                s = self.scenario()
                s.ticket(2)
                env, why = case(s)

                result = s.ralph("run", "1", **env)

                self.assertEqual(result.status, 1, result.output)
                text = read_draft(s)
                self.assertIn("Stopped before it could end cleanly:\n\n```text\n" + why, text)
                [run] = s.run_dirs()
                self.assertTrue(
                    result.output.endswith(f"ralph: the pull request draft is {run}/pull-request.md\n"),
                    result.output.splitlines()[-1],
                )

    def test_names_the_tickets_given_up_on_the_unreviewed_commits_and_commits_no_closed_ticket_accounts_for(self):
        s = self.scenario()
        s.ticket(2, title="Sort widgets")
        s.ticket(3, title="Sort by colour")
        s.agent_does(3, "no-promise")

        result = s.ralph("run", "1", RALPH_MAX_ATTEMPTS="1")

        self.assertEqual(result.status, 1, result.output)
        two, three = short_shas(s, "main..HEAD")
        base = s.git("rev-parse", "--short=9", "main")
        self.assertEqual(
            read_draft(s),
            f"Implements spec #1 on `spec/1-spec-widget-sorting`, from base `{base}`.\n"
            "\n"
            "## How the run ended\n"
            "\n"
            "Stopped before it could end cleanly:\n"
            "\n"
            "```text\n"
            "stopping, these tickets are open and nothing on the frontier can be implemented:\n"
            "#3 Sort by colour\n"
            "```\n"
            "\n"
            "## Tickets\n"
            "\n"
            "- #2 Sort widgets: closed after 1 attempt\n"
            f"  - `{two}` Implement ticket (#2)\n"
            "- #3 Sort by colour: given up after 1 attempt\n"
            "\n"
            "## Review rounds\n"
            "\n"
            "None.\n"
            "\n"
            "## Given up on\n"
            "\n"
            "- #3 Sort by colour\n"
            "\n"
            "## Unreviewed commits\n"
            "\n"
            f"- `{two}` Implement ticket (#2)\n"
            f"- `{three}` Implement ticket (#3)\n"
            "\n"
            "## Commits no closed ticket accounts for\n"
            "\n"
            f"- `{three}` Implement ticket (#3)\n",
        )
        self.assertEqual([s.issue(2)["state"], s.issue(3)["state"]], ["closed", "open"])

    def test_an_interrupted_run_writes_a_draft_too(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.agent_does(3, "interrupt")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 130, result.output)
        text = read_draft(s)
        self.assertIn("Stopped before it could end cleanly:\n\n```text\ninterrupted\n```\n", text)
        self.assertIn("- #3 Ticket 3: open after 1 attempt\n", text)
        [run] = s.run_dirs()
        self.assertTrue(
            result.output.endswith(f"ralph: interrupted\nralph: the pull request draft is {run}/pull-request.md\n"),
            result.output,
        )

    def test_a_review_round_that_broke_is_not_passed_off_as_clean(self):
        s = self.scenario()
        s.ticket(2)
        s.review_writes(1, "Found two problems")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        base = s.git("rev-parse", "--short=9", "main")
        self.assertIn(f"## Review rounds\n\n- Round 1, since `{base}`: did not finish\n", read_draft(s))

    def test_a_ticket_never_attempted_is_named_as_such(self):
        s = self.scenario()
        s.ticket(2)
        s.review_finds(1, finding("Sort is unstable"))

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="2")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("- #3 Sort is unstable, a fix ticket from review round 1: open, not attempted\n", read_draft(s))


if __name__ == "__main__":
    unittest.main()
