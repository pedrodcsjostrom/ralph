"""`ralph split <spec>`: an interactive session that splits a spec into tickets with the bundled to-tickets skill."""

import os
import unittest

from tests.harness import ScenarioTestCase

PLUGIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin")


class Split(ScenarioTestCase):
    def test_split_opens_an_interactive_session_on_the_spec_with_the_bundled_to_tickets_skill(self):
        s = self.scenario()

        result = s.ralph("split", "1")

        self.assertEqual(result.status, 1, result.output)
        check, session = s.calls("claude")[-2:]
        self.assertTrue(check.get("context"), check)
        self.assertTrue(session["interactive"])
        self.assertTrue(session["prompt"].startswith("/ralph:to-tickets #1\n\n"), session["prompt"])
        self.assertEqual(session["options"]["--plugin-dir"], [PLUGIN])
        self.assertEqual(session["options"]["--setting-sources"], ["project"])
        self.assertTrue(session["options"]["--strict-mcp-config"])
        # A human is present to approve commands, as in a watched iteration.
        self.assertEqual(session["options"]["--permission-mode"], ["acceptEdits"])
        self.assertEqual(s.events(), ["split #1"])

    def test_the_prompt_makes_the_ticket_contract_explicit(self):
        s = self.scenario()

        s.ralph("split", "1")

        prompt = " ".join(s.calls("claude")[-1]["prompt"].split())
        self.assertIn("- Spec: #1 in acme/widgets", prompt)
        self.assertIn("Every ticket is a sub-issue of the spec.", prompt)
        self.assertIn("repos/<repository>/issues/<spec>/sub_issues --method POST -F sub_issue_id=<id>", prompt)
        self.assertIn("Every ticket carries the `ready-for-agent` label.", prompt)
        self.assertIn("Every blocking edge is a native issue dependency", prompt)
        self.assertIn("issues/<ticket>/dependencies/blocked_by --method POST -F issue_id=<blocker id>", prompt)

    def test_split_reports_the_tickets_the_session_opened_and_how_to_run_them(self):
        s = self.scenario()
        s.split_creates("Sort by name", "Sort by date")

        result = s.ralph("split", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.issue(1)["sub_issues"], [2, 3])
        self.assertIn("ralph: spec #1 has 2 tickets; implement them with `ralph run 1`", result.output)


class SplitFails(ScenarioTestCase):
    def test_when_the_session_opens_no_ticket(self):
        s = self.scenario()

        result = s.ralph("split", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: the session ended and spec #1 still has no tickets", result.output)

    def test_when_the_session_fails(self):
        s = self.scenario()
        s.split_creates("Sort by name", status=3)

        result = s.ralph("split", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: the session splitting spec #1 ended with exit status 3; spec #1 has 1 ticket", result.output
        )

    def test_when_a_required_tool_is_missing(self):
        s = self.scenario()
        s.remove_tool("gh")

        result = s.ralph("split", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("(gh) is not on PATH", result.output)
        self.assertEqual(s.events(), [])


if __name__ == "__main__":
    unittest.main()
