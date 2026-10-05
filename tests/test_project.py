"""The project's checked-in configuration and project rules, and the help command."""

import unittest

from tests.harness import ScenarioTestCase


def configured(s, text):
    """Commits text as the project's configuration file."""
    s.commit_file(".ralph/config", text, "Configure ralph")


class Configuration(ScenarioTestCase):
    def test_the_verify_command_comes_from_the_configuration_file(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "verify = echo widget sort is broken; exit 3\nmax_attempts = 1\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "comment #2"])
        self.assertIn("widget sort is broken", s.issue(2)["comments"][0])

    def test_the_budgets_come_from_the_configuration_file(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked")
        configured(s, "# Budgets for this project\n\nmax_attempts = 3\nmax_iterations = 7\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #2", "agent #2", "agent #2"])
        self.assertIn("=== [3/7] ticket #2, attempt 3/3 ===", result.output)

    def test_an_environment_variable_overrides_the_file_for_one_run(self):
        s = self.scenario()
        s.ticket(2)
        s.agent_does(2, "blocked")
        configured(s, "max_attempts = 3\n")

        result = s.ralph("run", "1", RALPH_MAX_ATTEMPTS="1")

        self.assertEqual(s.events(), ["agent #2"])
        self.assertIn("giving up on #2 after 1 attempts", result.output)

    def test_an_empty_environment_variable_turns_the_files_verify_off_for_one_run(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "verify = exit 1\n")

        result = s.ralph("run", "1", RALPH_VERIFY="")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "review 1"])

    def test_an_unknown_key_stops_the_run_before_it_starts(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "max_attempts = 3\nmax_atempts = 1\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: .ralph/config: unknown key 'max_atempts' on line 2", result.output)
        self.assertEqual(s.calls("claude")[-1]["args"], ["auth", "status"])
        self.assertEqual(s.events(), [])
        self.assertEqual(s.branch(), "main")

    def test_a_malformed_value_stops_the_run_before_it_starts(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "max_review_rounds = three\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: .ralph/config: max_review_rounds must be a whole number of at least 1, not 'three'", result.output
        )
        self.assertEqual(s.events(), [])
        self.assertEqual(s.branch(), "main")

    def test_a_line_that_is_not_a_setting_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "verify: make check\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: .ralph/config line 1 is not `key = value`: 'verify: make check'", result.output)

    def test_every_problem_is_named_at_once(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "max_attempts = 0\nagent_flags = --model 'sonnet\n")

        result = s.ralph("run", "1", RALPH_MAX_ITERATIONS="many")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: cannot start:\n", result.output)
        self.assertIn("  - .ralph/config: max_attempts must be a whole number of at least 1, not '0'", result.output)
        self.assertIn("  - RALPH_MAX_ITERATIONS must be a whole number of at least 1, not 'many'", result.output)
        self.assertIn("  - .ralph/config: agent_flags must be flags as a shell would split them", result.output)

    def test_the_main_branch_comes_from_the_configuration_file(self):
        s = self.scenario()
        s.git("branch", "-m", "main", "trunk")
        s.ticket(2)
        configured(s, "main_branch = trunk\n")
        base = s.git("rev-parse", "HEAD")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.branch(), "spec/1-spec-widget-sorting")
        self.assertIn(f"base {base[:9]}", result.output)
        self.assertEqual(s.log("trunk..HEAD"), ["Implement ticket (#2)"])

    def test_the_run_base_comes_from_the_configuration_file(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "run_base = HEAD~1\n")
        first = s.git("rev-parse", "HEAD~1")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertIn(f"base {first[:9]}", result.output)
        [review] = [p for p in s.prompts() if "- Findings file:" in p]
        self.assertIn(f"- Fixed point, the commit to review the work against: {first}", review)

    def test_a_run_base_that_is_not_a_commit_stops_the_run(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "run_base = no-such-branch\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: the run base 'no-such-branch' (run_base) is not a commit in this repository", result.output
        )
        self.assertEqual(s.events(), [])
        self.assertEqual(s.branch(), "main")

    def test_extra_agent_flags_reach_every_agent_launch(self):
        s = self.scenario()
        s.ticket(2)
        configured(s, "agent_flags = --model sonnet --append-system-prompt 'be brief'\n")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        launches = [c["args"] for c in s.calls("claude") if "prompt" in c]
        self.assertEqual(len(launches), 2)
        for args in launches:
            self.assertEqual(args[-4:], ["--model", "sonnet", "--append-system-prompt", "be brief"])


class ProjectRules(ScenarioTestCase):
    def test_implement_rules_follow_the_generic_instructions_in_implement_prompts(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/rules/implement.md", "Run `make widgets` before committing.\n", "Implement rules")
        s.commit_file(".ralph/rules/review.md", "Check the widget vocabulary.\n", "Review rules")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        implement, review = s.prompts()
        generic = implement.index("# Ralph iteration")
        rules = implement.index("## Project rules\n\nRun `make widgets` before committing.\n")
        self.assertLess(generic, rules)
        self.assertLess(rules, implement.index("## Run context"))
        self.assertNotIn("Check the widget vocabulary.", implement)

        rules = review.index("## Project rules\n\nCheck the widget vocabulary.\n")
        self.assertLess(rules, review.index("## Run context"))
        self.assertNotIn("make widgets", review)

    def test_a_project_with_empty_rules_files_runs_normally(self):
        s = self.scenario()
        s.ticket(2)
        s.commit_file(".ralph/rules/implement.md", "\n", "Empty implement rules")
        s.commit_file(".ralph/rules/review.md", "", "Empty review rules")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #2", "close #2", "review 1"])
        for prompt in s.prompts():
            self.assertNotIn("## Project rules", prompt)

    def test_a_project_with_no_rules_files_runs_normally(self):
        s = self.scenario()
        s.ticket(2)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        for prompt in s.prompts():
            self.assertNotIn("## Project rules", prompt)


if __name__ == "__main__":
    unittest.main()
