"""The guard rails of an unattended run: attempts, verify, the checkout invariants and the iteration budget."""

import json
import unittest

from tests.harness import ScenarioTestCase


class Attempts(ScenarioTestCase):
    def test_a_ticket_that_fails_every_attempt_is_skipped_and_the_run_moves_on(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.agent_does(2, "blocked")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2", "agent #2", "comment #2", "agent #3", "close #3"])
        self.assertEqual(s.issue(2)["state"], "open")
        self.assertIn("giving up on #2 after 2 attempts", result.output)
        self.assertIn(
            "these tickets are open and nothing on the frontier can be implemented:\n#2 Ticket 2", result.output
        )

    def test_a_later_attempt_can_close_the_ticket(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked", "complete")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2", "agent #2", "close #2", "review 1"])
        self.assertIn("=== [2/30] ticket #2, attempt 2/2 ===", result.output)

    def test_the_attempt_budget_comes_from_the_environment(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked")

        result = s.ralph("run", "1", RALPH_MAX_ATTEMPTS="3")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2"] * 3)
        self.assertIn("giving up on #2 after 3 attempts", result.output)

    def test_a_budget_that_is_not_a_positive_whole_number_is_refused(self):
        for name in ("RALPH_MAX_ATTEMPTS", "RALPH_MAX_ITERATIONS"):
            for value in ("0", "two", "-1"):
                with self.subTest(name=name, value=value):
                    s = self.scenario()
                    s.ticket(2)

                    result = s.ralph("run", "1", **{name: value})

                    self.assertEqual(result.status, 1, result.output)
                    self.assertIn(f"ralph: {name} must be a whole number of at least 1, not {value!r}", result.output)
                    self.assertEqual(s.events(), [])


class Blocked(ScenarioTestCase):
    def test_the_reason_a_blocked_agent_gives_is_commented_on_the_ticket_for_the_next_attempt(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked", "complete")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2", "agent #2", "close #2", "review 1"])
        comment = s.issue(2)["comments"][0]
        self.assertEqual(
            comment,
            "ralph: attempt 1 ended blocked. The agent said:\n\n"
            "> Ticket #2 is half done: the spec does not say how to order equal widgets.",
        )
        # The next attempt reads it among the ticket's comments.
        self.assertIn(json.dumps(comment), s.prompts()[1])
        self.assertIn("ralph: #2 stays open, the agent reported it blocked", result.output)

    def test_agents_are_told_to_give_the_reason_in_their_final_message_and_never_to_comment(self):
        s = self.scenario()
        s.ticket(2)

        s.ralph("run", "1")

        implement, review = (" ".join(prompt.split()) for prompt in s.prompts())
        self.assertNotIn("gh issue comment", implement)
        self.assertIn("Do not create, close, label, comment on or edit any issue.", implement)
        self.assertIn("end your final message by saying what is done and what blocks the rest", implement)
        self.assertNotIn("gh issue comment", review)


class Verify(ScenarioTestCase):
    def test_a_failing_verify_keeps_the_ticket_open_and_comments_its_output(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1", RALPH_VERIFY="echo widget sort is broken; exit 3", RALPH_MAX_ATTEMPTS="1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2"])
        self.assertEqual(s.issue(2)["state"], "open")
        [comment] = s.issue(2)["comments"]
        self.assertEqual(
            comment,
            "ralph: `echo widget sort is broken; exit 3` failed after this attempt.\n\n```\nwidget sort is broken\n```",
        )
        self.assertIn("#2 stays open, `echo widget sort is broken; exit 3` failed", result.output)

    def test_the_next_attempt_reads_the_verify_failure(self):
        s = self.scenario()
        s.ticket(2)

        s.ralph("run", "1", RALPH_VERIFY="echo widget sort is broken; exit 3")

        self.assertEqual(s.events(), ["agent #2", "comment #2", "agent #2", "comment #2"])
        self.assertIn("widget sort is broken", s.prompts()[1])

    def test_the_comment_holds_only_the_tail_of_long_output(self):
        s = self.scenario()
        s.ticket(2)
        verify = "i=1; while [ $i -le 100 ]; do echo line $i; i=$((i+1)); done; exit 1"

        s.ralph("run", "1", RALPH_VERIFY=verify, RALPH_MAX_ATTEMPTS="1")

        [comment] = s.issue(2)["comments"]
        output = comment.split("```\n")[1].split("\n```")[0]
        self.assertEqual(output.splitlines(), [f"line {i}" for i in range(61, 101)])

    def test_a_passing_verify_lets_the_ticket_close(self):
        s = self.scenario()
        s.ticket(2)

        # Runs at the root of the checkout, after the agent's commit.
        result = s.ralph("run", "1", RALPH_VERIFY="test -f ticket-2.txt")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "review 1"])

    def test_verify_does_not_run_for_an_attempt_that_did_not_finish(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked")

        s.ralph("run", "1", RALPH_VERIFY="exit 1", RALPH_MAX_ATTEMPTS="1")

        self.assertEqual(s.events(), ["agent #2", "comment #2"])
        [comment] = s.issue(2)["comments"]
        self.assertTrue(comment.startswith("ralph: attempt 1 ended blocked."), comment)


class CheckoutInvariants(ScenarioTestCase):
    def test_an_agent_that_leaves_uncommitted_changes_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.agent_does(2, "dirty")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2"])
        self.assertIn(
            "ralph: iteration 1 (ticket #2) left uncommitted changes; inspect them, then rerun", result.output
        )
        self.assertNotEqual(s.status(), "")

    def test_an_agent_that_switches_branch_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.agent_does(2, "switch-branch")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2"])
        self.assertIn(
            "ralph: iteration 1 (ticket #2) left the checkout on elsewhere, off spec/1-spec-widget-sorting; "
            "switch back, then rerun",
            result.output,
        )

    def test_an_agent_that_detaches_head_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "detach")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2"])
        self.assertIn(
            "ralph: iteration 1 (ticket #2) left HEAD detached, off spec/1-spec-widget-sorting; "
            "switch back, then rerun",
            result.output,
        )

    def test_the_invariants_are_checked_before_verify_and_close(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "complete-dirty")

        result = s.ralph("run", "1", RALPH_VERIFY="exit 1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2"])
        self.assertIn("left uncommitted changes", result.output)


class IterationBudget(ScenarioTestCase):
    def test_exceeding_the_iteration_budget_stops_the_run_and_says_what_is_left(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.ticket(4, blocked_by=[3])

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2"])
        self.assertIn(
            "ralph: the iteration budget (1) is spent with work left; rerun to carry on. Still open:\n"
            "#3 Ticket 3\n#4 Ticket 4",
            result.output,
        )

    def test_a_run_whose_clean_review_is_its_last_iteration_succeeds(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="3")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "agent #3", "close #3", "review 1"])
        self.assertIn("=== [3/3] review round 1/3", result.output)

    def test_every_attempt_spends_an_iteration(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked", "blocked", "complete")

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="2", RALPH_MAX_ATTEMPTS="3")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2"] * 2)
        self.assertIn("=== [2/2] ticket #2, attempt 2/3 ===", result.output)
        self.assertIn("the iteration budget (2) is spent", result.output)


if __name__ == "__main__":
    unittest.main()
