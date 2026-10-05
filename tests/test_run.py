"""`ralph run <spec>`: an unattended run implements the frontier and closes tickets."""

import json
import os
import unittest

from tests.harness import ScenarioTestCase


class ImplementsTheFrontier(ScenarioTestCase):
    def test_tickets_are_implemented_in_frontier_order_and_closed(self):
        s = self.scenario()
        # 2 is blocked by 3, so 3 goes first although it has the higher number.
        s.ticket(2, blocked_by=[3])
        s.ticket(3)
        s.ticket(4)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #3", "close #3", "agent #2", "close #2", "agent #4", "close #4"])
        self.assertEqual(
            s.log("main..HEAD"),
            ["Implement ticket (#3)", "Implement ticket (#2)", "Implement ticket (#4)"],
        )
        for number in (2, 3, 4):
            self.assertEqual(s.issue(number)["state"], "closed")

    def test_unready_and_blocked_tickets_are_not_picked(self):
        s = self.scenario()
        s.ticket(2, labels=["ready-for-human"])
        s.ticket(3, blocked_by=[2])
        s.ticket(4, labels=[])
        s.ticket(5)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #5", "close #5"])
        self.assertIn("nothing on the frontier can be implemented", result.output)
        self.assertIn("#2 Ticket 2\n#3 Ticket 3\n#4 Ticket 4\n", result.output)
        self.assertNotIn("#5 Ticket 5", result.output)

    def test_a_ticket_is_picked_once_its_blocker_is_closed(self):
        s = self.scenario()
        s.ticket(2, blocked_by=[4])
        s.ticket(3, blocked_by=[9], state="open")
        s.ticket(4)
        s.ticket(9, state="closed")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #3", "close #3", "agent #4", "close #4", "agent #2", "close #2"])


class IntegrationBranch(ScenarioTestCase):
    def test_started_from_main_the_run_creates_the_integration_branch(self):
        s = self.scenario()
        s.ticket(2)
        main = s.git("rev-parse", "main")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.branch(), "spec/1-spec-widget-sorting")
        self.assertEqual(s.log("main..HEAD"), ["Implement ticket (#2)"])
        self.assertEqual(s.git("rev-parse", "main"), main)
        self.assertEqual(s.status(), "")

    def test_started_from_main_again_the_run_reuses_the_integration_branch(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.agent_does(3, "blocked")
        s.ralph("run", "1")
        s.git("switch", "-q", "main")
        s.agent_does(3, "complete")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.branch(), "spec/1-spec-widget-sorting")
        self.assertEqual(s.log("main..HEAD"), ["Implement ticket (#2)", "Implement ticket (#3)"])

    def test_started_from_another_branch_the_run_uses_it(self):
        s = self.scenario()
        s.ticket(2)
        s.git("switch", "-q", "-c", "my-work")
        s.commit_file("mine.txt", "mine\n", "My own start")
        main = s.git("rev-parse", "main")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.branch(), "my-work")
        self.assertEqual(s.log("main..my-work"), ["My own start", "Implement ticket (#2)"])
        self.assertEqual(s.git("rev-parse", "main"), main)
        self.assertEqual(s.git("branch", "--list", "spec/*"), "")

    def test_the_run_base_is_the_merge_base_with_main(self):
        s = self.scenario()
        s.ticket(2)
        base = s.git("rev-parse", "main")
        s.git("switch", "-q", "-c", "my-work")
        s.commit_file("mine.txt", "mine\n", "My own start")
        s.git("switch", "-q", "main")
        s.commit_file("later.txt", "later\n", "Main moves on")
        s.git("switch", "-q", "my-work")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertIn(f"base {base[:9]}", result.output)
        prompt = s.prompts()[0]
        self.assertIn("My own start", prompt)
        self.assertNotIn("Main moves on", prompt)


class RefusesToStart(ScenarioTestCase):
    def assertRefused(self, s, result, message):
        self.assertEqual(result.status, 1, result.output)
        self.assertIn(message, result.output)
        self.assertEqual(s.events(), [])
        self.assertEqual(s.branch(), "main")

    def test_when_a_required_tool_is_missing(self):
        for tool, message in [
            ("gh", "the GitHub CLI (gh) is not on PATH"),
            ("claude", "Claude Code (claude) is not on PATH"),
        ]:
            with self.subTest(tool=tool):
                s = self.scenario()
                s.ticket(2)
                s.remove_tool(tool)
                self.assertRefused(s, s.ralph("run", "1"), message)

    def test_when_git_is_missing(self):
        s = self.scenario()
        s.ticket(2)
        s.remove_tool("git")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("git is not on PATH", result.output)
        self.assertEqual(s.events(), [])

    def test_naming_every_missing_tool_at_once(self):
        s = self.scenario()
        s.remove_tool("gh")
        s.remove_tool("claude")

        result = s.ralph("run", "1")

        self.assertIn("the GitHub CLI (gh) is not on PATH", result.output)
        self.assertIn("Claude Code (claude) is not on PATH", result.output)

    def test_when_a_required_tool_is_not_logged_in(self):
        s = self.scenario()
        s.ticket(2)
        s.tracker_logged_in(False)
        self.assertRefused(s, s.ralph("run", "1"), "the GitHub CLI (gh) is not logged in; run `gh auth login`")

        s = self.scenario()
        s.ticket(2)
        s.agent_logged_in(False)
        self.assertRefused(s, s.ralph("run", "1"), "Claude Code (claude) is not logged in; run `claude auth login`")

    def test_on_a_dirty_working_tree(self):
        s = self.scenario()
        s.ticket(2)
        s.write("stray.txt", "stray\n")
        self.assertRefused(s, s.ralph("run", "1"), "the working tree is not clean")

    def test_on_a_detached_head(self):
        s = self.scenario()
        s.ticket(2)
        s.git("switch", "-q", "--detach")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("HEAD is detached", result.output)
        self.assertEqual(s.events(), [])

    def test_on_a_spec_with_no_tickets(self):
        s = self.scenario()
        self.assertRefused(s, s.ralph("run", "1"), "spec #1 has no tickets. Split it into tickets first")

    def test_outside_a_git_repository(self):
        s = self.scenario()
        s.ticket(2)
        s.work = os.path.join(s.root, "elsewhere")
        os.makedirs(s.work)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("is not inside a git repository", result.output)
        self.assertEqual(s.events(), [])


class ClosesOnlyCompletedTickets(ScenarioTestCase):
    def test_a_ticket_is_closed_with_a_comment_naming_its_commits(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        sha = s.git("rev-parse", "--short=9", "HEAD")
        closes = [c for c in s.calls("gh") if c.get("mutation") == "close"]
        self.assertEqual(closes[0]["comment"], f"Implemented by ralph on `spec/1-spec-widget-sorting`: {sha}")

    def test_a_ticket_is_not_closed_unless_the_agent_reports_it_complete_and_commits(self):
        for behaviour in ("no-promise", "no-commit", "blocked"):
            with self.subTest(behaviour=behaviour):
                s = self.scenario()
                s.ticket(2)
                s.ticket(3)
                s.agent_does(2, behaviour)

                result = s.ralph("run", "1", RALPH_MAX_ATTEMPTS="1")

                self.assertEqual(result.status, 1, result.output)
                self.assertEqual(s.events(), ["agent #2", "agent #3", "close #3"])
                self.assertEqual(s.issue(2)["state"], "open")
                self.assertIn(
                    "these tickets are open and nothing on the frontier can be implemented:\n#2 Ticket 2", result.output
                )

    def test_what_an_unfinished_ticket_blocks_never_starts(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3, blocked_by=[2])
        s.agent_does(2, "blocked")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "agent #2"])
        self.assertIn("#2 Ticket 2\n#3 Ticket 3", result.output)


class Rerun(ScenarioTestCase):
    def test_a_rerun_carries_on_from_the_tracker_without_a_state_file(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)
        s.ticket(4, blocked_by=[3])
        s.agent_does(3, "blocked")
        first = s.ralph("run", "1")
        self.assertEqual(first.status, 1, first.output)
        s.agent_does(3, "complete")

        second = s.ralph("run", "1")

        self.assertEqual(second.status, 0, second.output)
        self.assertEqual(
            s.events(),
            ["agent #2", "close #2", "agent #3", "agent #3", "agent #3", "close #3", "agent #4", "close #4"],
        )
        self.assertEqual(
            s.log("main..HEAD"), ["Implement ticket (#2)", "Implement ticket (#3)", "Implement ticket (#4)"]
        )
        # Only run logs are left behind, and git ignores them.
        self.assertEqual(sorted(os.listdir(os.path.join(s.work, ".ralph"))), ["runs"])
        self.assertEqual(s.status(), "")
        self.assertEqual(s.git("status", "--porcelain", "--ignored"), "!! .ralph/")


class WhatTheRunnerSees(ScenarioTestCase):
    def test_the_agents_prose_streams_to_the_terminal(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertIn("Working on ticket #2.", result.output)
        self.assertIn("ralph: closed #2", result.output)
        self.assertNotIn("not json", result.output)
        self.assertNotIn('"type"', result.output)

    def test_the_full_event_log_is_kept_in_the_run_directory(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3)

        result = s.ralph("run", "1")

        [run] = s.run_dirs()
        self.assertIn(f"logs in {run}", result.output)
        self.assertEqual(sorted(os.listdir(run)), ["01-ticket-2.jsonl", "02-ticket-3.jsonl"])
        with open(os.path.join(run, "01-ticket-2.jsonl")) as f:
            events = [json.loads(line) for line in f]
        self.assertEqual([e["type"] for e in events], ["system", "assistant", "assistant", "assistant", "result"])
        self.assertEqual(events[2]["message"]["content"][0]["name"], "Bash")

    def test_every_run_gets_its_own_run_directory(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked")
        s.ralph("run", "1")
        s.ralph("run", "1")

        self.assertEqual(len(s.run_dirs()), 2)


class TheAgent(ScenarioTestCase):
    def test_runs_headless_with_attribution_switched_off(self):
        s = self.scenario()
        s.ticket(2)

        s.ralph("run", "1")

        [call] = [c for c in s.calls("claude") if "prompt" in c]
        args = call["args"]
        self.assertIn("--print", args)
        self.assertEqual(args[args.index("--output-format") + 1], "stream-json")
        settings = json.loads(args[args.index("--settings") + 1])
        self.assertEqual(settings["attribution"], {"commit": "", "pr": ""})

    def test_the_prompt_is_the_generic_instructions_then_the_run_context(self):
        s = self.scenario()
        s.ticket(2)
        s.ticket(3, body="Sort widgets by name.", comments=["An earlier attempt got stuck on the sort key."])

        s.ralph("run", "1")

        prompt = s.prompts()[1]
        instructions = prompt.index("<promise>TICKET COMPLETE</promise>")
        context = prompt.index("## Run context")
        self.assertLess(instructions, context)
        for rule in (
            "<promise>TICKET BLOCKED</promise>",
            "Do not create or switch branches, push, merge, or open a pull request.",
            "Do not close, label or edit any issue.",
            "Never use `git stash`",
            "names the ticket as `(#<ticket>)`",
            "No `Co-Authored-By`",
            "Regenerate generated files",
            "Leave the working tree clean.",
        ):
            self.assertIn(rule, prompt[:context])
        run_context = prompt[context:]
        fixed_point = s.git("rev-parse", "HEAD~1")
        for line in (
            "- Spec: #1 in acme/widgets",
            "- Integration branch: spec/1-spec-widget-sorting",
            "- Ticket: #3",
            f"- Fixed point, the commit to review your work against: {fixed_point}",
            '"title": "Ticket 3"',
            '"url": "https://github.com/acme/widgets/issues/3"',
            "Sort widgets by name.",
            "An earlier attempt got stuck on the sort key.",
            "Implement ticket (#2)",
        ):
            self.assertIn(line, run_context)
        self.assertNotIn("Initial commit", run_context)


if __name__ == "__main__":
    unittest.main()
