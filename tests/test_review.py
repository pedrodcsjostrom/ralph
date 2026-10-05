"""Review rounds: once every ticket is closed, the work is reviewed and the findings come back as fix tickets."""

import json
import os
import unittest

from tests.harness import ScenarioTestCase


def finding(title, what="Equal widgets keep their order.", criteria=("Sorting is stable",)):
    return {"title": title, "what_to_build": what, "acceptance_criteria": list(criteria)}


class ReviewRounds(ScenarioTestCase):
    def test_findings_become_fix_tickets_that_are_implemented_until_a_review_is_clean(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.review_finds(1, finding("Sort is unstable"))

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(
            s.events(),
            [
                "agent #2",
                "close #2",
                "agent #3",
                "close #3",
                "review 1",
                "create #4",
                "link #4",
                "agent #4",
                "close #4",
                "review 2",
            ],
        )
        self.assertIn("review finding is now #4: Sort is unstable", result.output)
        self.assertIn("complete after 5 iterations", result.output)

    def test_each_later_round_reviews_only_the_fixes_of_the_round_before(self):
        s = self.scenario()
        s.ticket(2)
        s.review_finds(1, finding("Sort is unstable"), finding("Sort ignores case"))
        s.review_finds(2, finding("Stable sort is slow"))
        base = s.git("rev-parse", "main")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        after_tickets = s.git("rev-parse", "HEAD~3")
        after_round_1 = s.git("rev-parse", "HEAD~1")
        reviews = [c["prompt"] for c in s.calls("claude") if "review" in c]
        self.assertEqual(len(reviews), 3)
        self.assertIn(f"- Fixed point, the commit to review the work against: {base}\n", reviews[0])
        self.assertNotIn("This diff holds only", reviews[0])
        self.assertIn(f"- Fixed point, the commit to review the work against: {after_tickets}\n", reviews[1])
        self.assertIn(
            "- This diff holds only the fixes for the previous review round's fix tickets: #3, #4", reviews[1]
        )
        self.assertIn(f"- Fixed point, the commit to review the work against: {after_round_1}\n", reviews[2])
        self.assertIn("- This diff holds only the fixes for the previous review round's fix tickets: #5", reviews[2])
        self.assertIn(f"review round 2/3, since {after_tickets[:9]}", result.output)

    def test_the_review_prompt_is_the_skill_invocation_the_generic_review_instructions_then_the_run_context(self):
        s = self.scenario()
        s.ticket(2)

        s.ralph("run", "1")

        [review] = [c for c in s.calls("claude") if "review" in c]
        prompt = review["prompt"]
        self.assertIn("\n\n# Ralph review\n", prompt)
        context = prompt[prompt.index("## Run context") :]
        [run] = s.run_dirs()
        self.assertEqual(
            context.strip().splitlines()[2:],
            [
                "- Spec: #1 in acme/widgets",
                "- Integration branch: spec/1-spec-widget-sorting",
                f"- Fixed point, the commit to review the work against: {s.git('rev-parse', 'main')}",
                "- Review round: 1",
                f"- Findings file: {run}/review-1.json",
            ],
        )

    def test_a_fix_ticket_has_the_structure_a_split_produces(self):
        s = self.scenario()
        s.ticket(2)
        s.review_finds(
            1, finding("Sort is unstable", "Equal widgets swap places.", ["Equal widgets keep their order", "Tested"])
        )

        s.ralph("run", "1")

        fix = s.issue(3)
        self.assertEqual(fix["title"], "Sort is unstable")
        self.assertEqual(fix["labels"], ["ready-for-agent"])
        self.assertEqual(
            fix["body"],
            "## Parent\n\n#1\n\n"
            "## What to build\n\nEqual widgets swap places.\n\n"
            "## Acceptance criteria\n\n- [ ] Equal widgets keep their order\n- [ ] Tested\n\n"
            "## Blocked by\n\nNone (can start immediately)\n",
        )
        self.assertIn(3, s.issue(1)["sub_issues"])

    def test_a_round_that_finds_nothing_ends_the_run_successfully(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "review 1"])
        self.assertIn("ralph: review round 1 found nothing", result.output)
        self.assertIn("Spec #1 is implemented and reviewed on spec/1-spec-widget-sorting", result.output)

    def test_with_nothing_committed_since_the_fixed_point_there_is_nothing_to_review(self):
        s = self.scenario()
        s.ticket(2, state="closed")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), [])
        self.assertIn("nothing to review since", result.output)

    def test_each_reviews_findings_are_kept_in_the_run_directory(self):
        s = self.scenario()
        s.ticket(2)
        written = '[{"title": "Sort is unstable", "what_to_build": "x", "acceptance_criteria": ["y"]}]\n'
        s.review_writes(1, written)

        s.ralph("run", "1")

        [run] = s.run_dirs()
        with open(os.path.join(run, "review-1.json")) as f:
            self.assertEqual(f.read(), written)
        with open(os.path.join(run, "review-2.json")) as f:
            self.assertEqual(f.read(), "[]")


class BrokenReviews(ScenarioTestCase):
    def test_a_missing_or_malformed_findings_file_stops_the_run(self):
        cases = {
            "no file": (None, "wrote no findings to"),
            "not JSON": ("Found two problems:\n- sort", "that are not valid JSON"),
            "not an array": ('{"title": "Sort is unstable"}', "expected a JSON array of findings"),
            "no title": ('[{"what_to_build": "x", "acceptance_criteria": ["y"]}]', "finding 1 needs a non-empty"),
            "no criteria": (
                '[{"title": "t", "what_to_build": "x", "acceptance_criteria": ["y"]},'
                ' {"title": "t", "what_to_build": "x", "acceptance_criteria": []}]',
                "finding 2 needs acceptance_criteria",
            ),
        }
        for case, (text, why) in cases.items():
            with self.subTest(case):
                s = self.scenario()
                s.ticket(2)
                s.review_writes(1, text)

                result = s.ralph("run", "1")

                self.assertEqual(result.status, 1, result.output)
                self.assertEqual(s.events(), ["agent #2", "close #2", "review 1"])
                self.assertIn("ralph: review round 1 ", result.output)
                self.assertIn(why, result.output)
                self.assertNotIn("complete after", result.output)


class TheReviewIteration(ScenarioTestCase):
    def test_a_review_that_leaves_uncommitted_changes_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.review_writes(1, json.dumps([finding("Sort is unstable")]), also="dirty")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "review 1"])
        self.assertIn("ralph: iteration 2 (review round 1) left uncommitted changes", result.output)

    def test_a_review_that_switches_branch_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.review_writes(1, "[]", also="switch-branch")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: iteration 2 (review round 1) left the checkout on elsewhere, off spec/1-spec-widget-sorting",
            result.output,
        )

    def test_a_review_that_commits_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        s.review_writes(1, "[]", also="commit")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: iteration 2 (review round 1) made commits, but a review changes nothing", result.output)


class Budgets(ScenarioTestCase):
    def test_reviews_that_keep_finding_things_stop_at_the_review_round_budget(self):
        s = self.scenario()
        s.ticket(2)
        s.review_finds(1, finding("More"))
        s.review_finds(2, finding("Even more"))

        result = s.ralph("run", "1", RALPH_MAX_REVIEW_ROUNDS="2")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(
            s.events(),
            ["agent #2", "close #2", "review 1", "create #3", "link #3", "agent #3", "close #3", "review 2"]
            + ["create #4", "link #4", "agent #4", "close #4"],
        )
        since = s.git("rev-parse", "--short=9", "HEAD~1")
        unreviewed = s.git("rev-parse", "--short=9", "HEAD")
        self.assertIn(
            f"ralph: the review round budget (2) is spent; these commits since {since} are unreviewed:\n"
            f"{unreviewed} Implement ticket (#4)\n",
            result.output,
        )

    def test_the_review_round_budget_must_be_a_positive_whole_number(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1", RALPH_MAX_REVIEW_ROUNDS="0")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("RALPH_MAX_REVIEW_ROUNDS must be a whole number of at least 1, not '0'", result.output)
        self.assertEqual(s.events(), [])

    def test_a_review_needs_an_iteration_from_the_budget(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2"])
        base = s.git("rev-parse", "--short=9", "main")
        head = s.git("rev-parse", "--short=9", "HEAD")
        self.assertIn(
            "ralph: the iteration budget (1) is spent before review round 1; rerun to carry on. "
            f"These commits since {base} are unreviewed:\n{head} Implement ticket (#2)\n",
            result.output,
        )

    def test_a_review_spends_an_iteration(self):
        s = self.scenario()
        s.ticket(2)
        s.review_finds(1, finding("Sort is unstable"))

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="2")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "review 1", "create #3", "link #3"])
        self.assertIn(
            "the iteration budget (2) is spent with work left; rerun to carry on. Still open:\n#3 Sort is unstable",
            result.output,
        )


class TheRunRecord(ScenarioTestCase):
    def test_the_run_directory_records_each_ticket_and_review_round(self):
        s = self.scenario()
        s.ticket(2, title="Sort widgets")
        s.review_finds(1, finding("Sort is unstable"))

        s.ralph("run", "1")

        [run] = s.run_dirs()
        with open(os.path.join(run, "run.json")) as f:
            record = json.load(f)
        base = s.git("rev-parse", "main")
        first = s.git("rev-parse", "HEAD~1")
        fix = s.git("rev-parse", "HEAD")
        self.assertEqual(
            record,
            {
                "spec": 1,
                "branch": "spec/1-spec-widget-sorting",
                "base": base,
                "tickets": [
                    {
                        "number": 2,
                        "title": "Sort widgets",
                        "from_review_round": None,
                        "attempts": 1,
                        "outcome": "closed",
                        "commits": [first],
                    },
                    {
                        "number": 3,
                        "title": "Sort is unstable",
                        "from_review_round": 1,
                        "attempts": 1,
                        "outcome": "closed",
                        "commits": [fix],
                    },
                ],
                "review_rounds": [
                    {
                        "round": 1,
                        "fixed_point": base,
                        "head": first,
                        "findings_file": f"{run}/review-1.json",
                        "resolves": [],
                        "fix_tickets": [3],
                        "finished": True,
                    },
                    {
                        "round": 2,
                        "fixed_point": first,
                        "head": fix,
                        "findings_file": f"{run}/review-2.json",
                        "resolves": [3],
                        "fix_tickets": [],
                        "finished": True,
                    },
                ],
                "outcome": "complete",
                "reason": None,
                "unreviewed": [],
            },
        )

    def test_a_stopped_run_records_why_and_what_is_unreviewed(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.agent_does(3, "blocked")

        s.ralph("run", "1", RALPH_MAX_ATTEMPTS="1")

        [run] = s.run_dirs()
        with open(os.path.join(run, "run.json")) as f:
            record = json.load(f)
        self.assertEqual(record["outcome"], "stopped")
        self.assertIn("nothing on the frontier can be implemented", record["reason"])
        self.assertEqual([t["outcome"] for t in record["tickets"]], ["closed", "given up"])
        self.assertEqual(record["unreviewed"], [s.git("rev-parse", "HEAD")])
        self.assertEqual(record["review_rounds"], [])


if __name__ == "__main__":
    unittest.main()
