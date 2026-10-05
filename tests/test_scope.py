"""Agents at project scope with the bundled skills (ADR 0001, ADR 0002).

Every agent ralph launches, headless or interactive, loads the bundled `ralph`
plugin for that session only and runs with the runner's user-level settings,
instructions, memory and skills switched off. These tests assert the command
line the fake agent receives; tests/fakes/claude.py models how the real CLI
reads it, including options that take several values.
"""

import json
import os
import unittest

from tests.harness import ROOT, ScenarioTestCase

PLUGIN = os.path.join(ROOT, "plugin")
BUNDLED = ("ralph:code-review", "ralph:implement", "ralph:tdd", "ralph:to-tickets")


def option(args, name):
    """The value given to option name; it must be given exactly once."""
    values = [args[i + 1] for i, a in enumerate(args) if a == name]
    assert len(values) == 1, (name, args)
    return values[0]


def launches(s):
    """The command lines of the iterations and sessions, not of the start-up check."""
    return [c["args"] for c in s.calls("claude") if "ticket" in c or "review" in c]


class ProjectScope(ScenarioTestCase):
    def assert_project_scope(self, s, args):
        self.assertEqual(option(args, "--plugin-dir"), PLUGIN)
        self.assertEqual(option(args, "--setting-sources"), "project")
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(option(args, "--permission-mode"), "auto")
        settings = json.loads(option(args, "--settings"))
        self.assertIs(settings["autoMemoryEnabled"], False)
        self.assertEqual(settings["attribution"], {"commit": "", "pr": ""})
        # Instructions in the directories above the project count as project memory to Claude Code
        # (~/AGENTS.md, ~/CLAUDE.md), so each ancestor's are excluded; the project's own are not.
        parent = os.path.dirname(s.work)
        excludes = settings["claudeMdExcludes"]
        for directory in (parent, os.path.dirname(parent)):
            self.assertIn(directory + "/*.md", excludes)
            self.assertIn(directory + "/.claude/**", excludes)
        self.assertIn("/*.md", excludes)
        self.assertIn("/.claude/**", excludes)
        self.assertFalse([e for e in excludes if e.startswith(s.work + "/")], excludes)

    def test_headless_iterations_load_the_plugin_for_the_session_only_at_project_scope(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        implement, review = launches(s)
        for args in (implement, review):
            self.assert_project_scope(s, args)
            self.assertIn("--print", args)
            self.assertIn("--no-session-persistence", args)

    def test_a_watched_session_loads_the_plugin_for_the_session_only_at_project_scope(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 0, result.output)
        [session] = launches(s)
        self.assert_project_scope(s, session)
        self.assertNotIn("--print", session)

    def test_agents_do_not_inherit_the_claude_code_session_ralph_was_started_from(self):
        s = self.scenario()
        s.ticket(2)
        inside_claude_code = {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "CLAUDE_CODE_SESSION_ID": "parent",
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/parent.sock",
        }

        result = s.ralph("run", "1", **inside_claude_code)

        self.assertEqual(result.status, 0, result.output)
        for call in s.calls("claude"):
            self.assertEqual(call["env"], {}, call["args"])

    def test_the_projects_flags_can_end_in_an_option_taking_several_values(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/config", "agent_flags = --allowedTools Read Bash\n", "Configure ralph")

        watched = s.ralph("watch", "1")

        self.assertEqual(watched.status, 0, watched.output)
        session = s.calls("claude")[-1]
        self.assertEqual(session["options"]["--allowedTools"], ["Read", "Bash"])
        self.assertIn("- Ticket: #2", session["prompt"])


class BundledSkills(ScenarioTestCase):
    def test_implement_iterations_invoke_the_bundled_implement_skill_on_their_ticket(self):
        s = self.scenario()
        s.ticket(2)

        s.ralph("watch", "1")
        s.ralph("run", "1")

        watched, unattended = [c["prompt"] for c in s.calls("claude") if "ticket" in c]
        self.assertTrue(unattended.startswith("/ralph:implement #2\n\n# Ralph iteration\n"), unattended)
        self.assertTrue(watched.startswith("/ralph:implement #2\n\n# Ralph iteration\n"), watched)

    def test_review_iterations_invoke_the_bundled_code_review_skill_since_the_fixed_point(self):
        s = self.scenario()
        s.ticket(2)
        base = s.git("rev-parse", "HEAD")

        s.ralph("run", "1")

        [review] = [c["prompt"] for c in s.calls("claude") if "review" in c]
        self.assertTrue(review.startswith(f"/ralph:code-review {base}\n\n# Ralph review\n"), review)


class StartCheck(ScenarioTestCase):
    def test_a_run_starts_by_checking_the_agent_resolves_the_bundled_skills_with_the_launch_flags(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/config", "agent_flags = --model opus\n", "Configure ralph")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        check = [c for c in s.calls("claude") if c.get("context")]
        self.assertEqual(len(check), 1)
        self.assertEqual(option(check[0]["args"], "--plugin-dir"), PLUGIN)
        self.assertEqual(option(check[0]["args"], "--model"), "opus")
        self.assertEqual(s.calls("claude").index(check[0]), 1, "the check comes before any iteration")

    def test_a_run_fails_at_start_when_a_bundled_skill_cannot_be_resolved(self):
        s = self.scenario()
        s.ticket(2)
        plugin = s.use_ralph_copy()
        os.rename(os.path.join(plugin, "skills", "implement"), os.path.join(s.root, "implement"))

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: Claude Code cannot resolve the bundled skill ralph:implement from the plugin at "
            f"{plugin}; this copy of ralph is incomplete",
            result.output,
        )
        self.assertEqual(s.events(), [])
        self.assertEqual(s.branch(), "main")
        self.assertEqual(s.run_dirs(), [])

    def test_a_watch_fails_at_start_when_the_plugin_is_missing(self):
        s = self.scenario()
        s.ticket(2)
        plugin = s.use_ralph_copy()
        os.rename(plugin, os.path.join(s.root, "plugin-elsewhere"))

        result = s.ralph("watch", "1")

        self.assertEqual(result.status, 1, result.output)
        missing = ", ".join(BUNDLED)
        self.assertIn(f"ralph: Claude Code cannot resolve the bundled skills {missing} from the plugin", result.output)
        self.assertEqual(s.events(), [])

    def test_a_run_fails_at_start_when_claude_code_ignores_ralphs_settings(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_ignores_settings()

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: Claude Code ignored the settings ralph launches agents with (auto memory is still on), "
            "so agents would not run at project scope; check that `claude --version` is up to date",
            result.output,
        )
        self.assertEqual(s.events(), [])

    def test_a_run_fails_at_start_when_claude_code_rejects_the_launch_flags(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/config", "agent_flags = --no-such-flag\n", "Configure ralph")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: Claude Code could not start with ralph's launch flags and the project's agent_flags", result.output
        )
        self.assertIn("error: unknown option '--no-such-flag'", result.output)
        self.assertEqual(s.events(), [])


if __name__ == "__main__":
    unittest.main()
