"""`ralph watch <spec>`: an interactive session on the ticket an unattended run would implement next."""

import json
import unittest

from tests.harness import ScenarioTestCase


class Watch(ScenarioTestCase):
    def test_watch_opens_an_interactive_session_on_the_ticket_a_run_would_pick_next(self):
        s = self.scenario()
        # 2 is blocked by 3, so a run would implement 3 first although it has the higher number.
        s.ticket(2, blocked_by=[3])
        s.ticket(3)
        s.ticket(4)

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #3"])
        session = s.calls("claude")[-1]
        self.assertTrue(session["interactive"])
        self.assertNotIn("--print", session["args"])
        self.assertIn("- Ticket: #3", session["prompt"])
        self.assertIn("ralph: ticket #3 of spec #1 on spec/1-spec-widget-sorting", result.output)

    def test_the_session_starts_from_the_composed_prompt_saying_a_human_is_present(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/rules/implement.md", "Run `make check` before every commit.\n", "Add project rules")

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 0, result.output)
        prompt = s.calls("claude")[-1]["prompt"]
        self.assertTrue(prompt.startswith("/ralph:implement #2\n\n# Ralph iteration\n"), prompt)
        self.assertIn("## Project rules\n\nRun `make check` before every commit.\n", prompt)
        self.assertIn(
            "- A human is watching this iteration and will close the ticket: you may ask them questions.\n", prompt
        )
        self.assertLess(prompt.index("## Project rules"), prompt.index("## Run context"))
        self.assertLess(prompt.index("## Run context"), prompt.index("A human is watching"))

    def test_an_unattended_runs_prompt_has_no_human_present(self):
        s = self.scenario()
        s.ticket(2)

        s.ralph("run", "1")

        self.assertNotIn("A human is watching", s.prompts()[0])

    def test_the_session_is_launched_like_an_unattended_iteration_with_the_projects_flags(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/config", "agent_flags = --model opus\n", "Configure ralph")

        s.ralph("watch", "1")

        args = s.calls("claude")[-1]["args"]
        self.assertEqual(args[args.index("--permission-mode") + 1], "auto")
        self.assertEqual(json.loads(args[args.index("--settings") + 1])["attribution"], {"commit": "", "pr": ""})
        self.assertEqual(s.calls("claude")[-1]["options"]["--model"], ["opus"])
        self.assertNotIn("--output-format", args)

    def test_watch_closes_nothing_and_says_how_to_close_the_ticket(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2"])
        self.assertEqual(s.issue(2)["state"], "open")
        self.assertEqual(s.issue(2)["comments"], [])
        self.assertEqual(s.log("main..HEAD"), ["Implement ticket (#2)"])
        self.assertEqual(s.run_dirs(), [])
        self.assertIn("When the work is good, close it: gh issue close 2 --repo acme/widgets", result.output)

    def test_watch_uses_the_branch_it_is_started_on(self):
        s = self.scenario()
        s.ticket(2)
        s.git("switch", "-q", "-c", "my-branch")

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.branch(), "my-branch")
        self.assertIn("- Integration branch: my-branch", s.calls("claude")[-1]["prompt"])


class WatchRefuses(ScenarioTestCase):
    def test_when_nothing_is_on_the_frontier(self):
        s = self.scenario()
        s.ticket(2, labels=["ready-for-human"])
        s.ticket(3, blocked_by=[2])

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: no ticket of spec #1 is on the frontier", result.output)
        self.assertEqual(s.events(), [])

    def test_on_a_dirty_working_tree(self):
        s = self.scenario()
        s.ticket(2)
        s.write("README.md", "changed\n")

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("the working tree is not clean", result.output)
        self.assertEqual(s.events(), [])

    def test_when_a_required_tool_is_missing(self):
        s = self.scenario()
        s.ticket(2)
        s.remove_tool("gh")

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("(gh) is not on PATH", result.output)
        self.assertEqual(s.events(), [])

    def test_when_the_session_fails(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "crash")

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: the session on #2 ended with exit status 3; #2 stays open", result.output)
        self.assertNotIn("close it", result.output)


if __name__ == "__main__":
    unittest.main()
