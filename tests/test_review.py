"""Review rounds: once every ticket is closed, the work is reviewed and the findings come back as fix tickets."""

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


if __name__ == "__main__":
    unittest.main()
