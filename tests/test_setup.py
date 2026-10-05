"""Set-up, run as a maintainer runs it: from a clone of ralph, on a scratch project.

The clone is a copy of this checkout's ralph committed in a scratch repository
that also stands in for the public ralph repository, so a release is a tag on
it and the wrapper set-up writes fetches the code under test from it.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from tests.harness import REPO, ROOT, Result, Scenario, ScenarioTestCase

VERSION = "v0.1.0"


class SetupScenario(Scenario):
    def __init__(self, root):
        self.clone = os.path.join(root, "ralph-clone")
        self.cache = os.path.join(root, "cache")
        super().__init__(root)
        for part in ("bin", "src", "plugin", "wrapper"):
            shutil.copytree(
                os.path.join(ROOT, part), os.path.join(self.clone, part), ignore=shutil.ignore_patterns("__pycache__")
            )
        self.git_in(self.clone, "init", "-q")
        self.git_in(self.clone, "add", "-A")
        self.git_in(self.clone, "commit", "-q", "-m", "ralph")
        self.entry_point = os.path.join(self.clone, "bin", "ralph")

    def env(self, **extra):
        defaults = {"RALPH_REPOSITORY": "file://" + self.clone, "XDG_CACHE_HOME": self.cache}
        defaults.update(extra)
        return super().env(**defaults)

    def git_in(self, directory, *args):
        return subprocess.run(
            ("git",) + args, cwd=directory, env=self.env(), check=True, stdout=subprocess.PIPE, text=True
        ).stdout.strip()

    def release(self, version=VERSION):
        self.git_in(self.clone, "tag", version)

    def setup(self, *args, cwd=None, **env):
        return self._python(self.entry_point, ("setup",) + args, cwd, env)

    def wrapper(self, *args, cwd=None, **env):
        return self._python(os.path.join(self.work, "ralph"), args, cwd, env)

    def _python(self, script, args, cwd, env):
        proc = subprocess.run(
            (sys.executable, script) + tuple(args),
            cwd=cwd or self.work,
            env=self.env(**env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        return Result(proc.returncode, proc.stdout)

    def read(self, path):
        with open(os.path.join(self.work, path), encoding="utf-8") as f:
            return f.read()


class Setup(ScenarioTestCase):
    def scenario(self):
        root = tempfile.mkdtemp(prefix="ralph-setup-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return SetupScenario(os.path.realpath(root))

    def test_a_fresh_project_runs_the_wrapper_and_its_help_after_setup(self):
        s = self.scenario()
        s.release()

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        help_ = s.wrapper("help")
        self.assertEqual(help_.status, 0, help_.output)
        self.assertIn("ralph run <spec>", help_.output)
        self.assertEqual(s.read(".ralph/pin"), VERSION + "\n")
        self.assertTrue(os.access(os.path.join(s.work, "ralph"), os.X_OK))

    def test_a_clone_that_is_not_at_a_release_sets_nothing_up(self):
        s = self.scenario()

        result = s.setup()

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(f"ralph: the ralph clone at {s.clone} is not at a release", result.output)
        self.assertEqual(s.status(), "")

    def test_a_release_missing_from_the_public_repository_sets_nothing_up(self):
        s = self.scenario()
        s.release()
        public = os.path.join(s.root, "public")
        os.makedirs(public)
        s.git_in(public, "init", "-q")

        result = s.setup(RALPH_REPOSITORY="file://" + public)

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            f"ralph: {VERSION} is not released in file://{public}; push the tag there, then rerun", result.output
        )
        self.assertEqual(s.status(), "")

    def test_setup_scaffolds_the_configuration_and_empty_project_rules(self):
        s = self.scenario()
        s.release()

        self.assertEqual(s.setup().status, 0)

        config = s.read(".ralph/config")
        for key in ("verify", "main_branch", "run_base", "max_attempts", "max_review_rounds", "max_iterations"):
            self.assertIn(f"\n# {key} =", config)
        self.assertNotRegex(config, r"(?m)^[^#\n]")  # every key is left at its default
        self.assertEqual(s.read(".ralph/rules/implement.md"), "")
        self.assertEqual(s.read(".ralph/rules/review.md"), "")
        s.ticket(2)
        s.git("add", "-A")
        s.git("commit", "-q", "-m", "Set up ralph")
        run = s.ralph("run", "1")
        self.assertEqual(run.status, 0, run.output)

    def test_run_logs_are_ignored_while_pin_configuration_and_rules_are_tracked(self):
        s = self.scenario()
        s.release()
        self.assertEqual(s.setup().status, 0)
        s.write(".ralph/runs/20260101-000000/01-ticket-2.jsonl", "{}\n")

        s.git("add", "-A")

        tracked = s.git("diff", "--cached", "--name-only").splitlines()
        for path in ("ralph", ".ralph/pin", ".ralph/config", ".ralph/rules/implement.md", ".ralph/rules/review.md"):
            self.assertIn(path, tracked)
        self.assertFalse([p for p in tracked if p.startswith(".ralph/runs/")], tracked)

    def test_setup_creates_the_label_the_frontier_relies_on(self):
        s = self.scenario()
        s.release()

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        self.assertIn("ready-for-agent", s.labels())
        self.assertEqual(s.events(), ["label ready-for-agent"])
        self.assertIn(f"  created the ready-for-agent label on {REPO}\n", result.output)

    def test_setup_writes_short_issue_tracker_instructions_for_github(self):
        s = self.scenario()
        s.release()

        self.assertEqual(s.setup().status, 0)

        instructions = s.read("docs/agents/issue-tracker.md")
        self.assertIn("# Issue tracker: GitHub", instructions)
        self.assertIn("`ready-for-agent`", instructions)
        self.assertIn("sub_issues", instructions)
        self.assertIn("dependencies/blocked_by", instructions)
        self.assertLessEqual(len(instructions.splitlines()), 40)

    def test_setup_adds_a_short_section_pointing_at_help_to_a_new_claude_md(self):
        s = self.scenario()
        s.release()

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        section = self.ralph_section(s.read("CLAUDE.md"))
        self.assertIn("`./ralph help`", section)
        self.assertIn("docs/agents/issue-tracker.md", section)
        self.assertLessEqual(len(section.splitlines()), 12)
        self.assertFalse(os.path.exists(os.path.join(s.work, "AGENTS.md")))

    def test_setup_adds_the_section_to_the_end_of_existing_agent_instructions(self):
        s = self.scenario()
        s.release()
        s.commit_file("AGENTS.md", "# Widgets\n\nSort widgets carefully.\n", "Agent instructions")

        self.assertEqual(s.setup().status, 0)

        instructions = s.read("AGENTS.md")
        self.assertTrue(instructions.startswith("# Widgets\n\nSort widgets carefully.\n\n<!-- ralph"), instructions)
        self.assertIn("`./ralph help`", self.ralph_section(instructions))
        self.assertFalse(os.path.exists(os.path.join(s.work, "CLAUDE.md")))

    def test_claude_md_gets_the_section_when_both_instruction_files_exist(self):
        s = self.scenario()
        s.release()
        s.commit_file("AGENTS.md", "# For agents\n", "Agent instructions")
        s.commit_file("CLAUDE.md", "# For Claude\n", "Claude instructions")

        self.assertEqual(s.setup().status, 0)

        self.assertEqual(s.read("AGENTS.md"), "# For agents\n")
        self.assertIn("`./ralph help`", self.ralph_section(s.read("CLAUDE.md")))

    def test_a_claude_md_linked_to_agents_md_stays_a_link(self):
        s = self.scenario()
        s.release()
        s.commit_file("AGENTS.md", "# Widgets\n", "Agent instructions")
        os.symlink("AGENTS.md", os.path.join(s.work, "CLAUDE.md"))

        self.assertEqual(s.setup().status, 0)

        self.assertEqual(os.readlink(os.path.join(s.work, "CLAUDE.md")), "AGENTS.md")
        self.assertIn("`./ralph help`", self.ralph_section(s.read("AGENTS.md")))

    def test_issue_tracker_instructions_ralph_did_not_write_are_kept_and_reported(self):
        s = self.scenario()
        s.release()
        s.commit_file("docs/agents/issue-tracker.md", "# Issue tracker: ours\n", "Our tracker")

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.read("docs/agents/issue-tracker.md"), "# Issue tracker: ours\n")
        self.assertIn("kept docs/agents/issue-tracker.md, which ralph did not write", result.output)

    def ralph_section(self, text):
        """The ralph section of agent instructions, markers included; fails unless there is exactly one."""
        self.assertEqual(text.count("<!-- ralph:begin"), 1, text)
        self.assertEqual(text.count("<!-- ralph:end -->"), 1, text)
        return text[text.index("<!-- ralph:begin") : text.index("<!-- ralph:end -->") + len("<!-- ralph:end -->")]


class GlobalRalph(ScenarioTestCase):
    """The clone's bin/ralph linked onto PATH, as the README tells a maintainer to, and run by name."""

    scenario = Setup.scenario

    def on_path(self, s):
        os.symlink(s.entry_point, os.path.join(s.bin, "ralph"))
        os.symlink(sys.executable, os.path.join(s.bin, "python3"))

    def run_by_name(self, s, *args, cwd):
        proc = subprocess.run(
            ("ralph",) + args, cwd=cwd, env=s.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        return Result(proc.returncode, proc.stdout)

    def test_ralph_on_path_shows_help_documenting_setup_from_any_directory(self):
        s = self.scenario()
        self.on_path(s)
        elsewhere = os.path.join(s.root, "elsewhere")
        os.makedirs(elsewhere)

        result = self.run_by_name(s, "help", cwd=elsewhere)

        self.assertEqual(result.status, 0, result.output)
        maintainer = result.output.split("\nMaintainer commands\n")[1]
        self.assertIn("\n  ralph setup [--pin <tag>] [<directory>]\n", maintainer)
        self.assertIn("Sets the git repository holding <directory>", " ".join(maintainer.split()))
        self.assertIn("ln -s <clone>/bin/ralph ~/.local/bin/ralph", " ".join(maintainer.split()))

    def test_ralph_on_path_sets_up_the_project_it_is_run_in(self):
        s = self.scenario()
        s.release()
        self.on_path(s)
        subdir = os.path.join(s.work, "src")
        os.makedirs(subdir)

        result = self.run_by_name(s, "setup", cwd=subdir)

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.read(".ralph/pin"), VERSION + "\n")
        self.assertFalse(os.path.exists(os.path.join(subdir, ".ralph")))


class SetupAgain(ScenarioTestCase):
    scenario = Setup.scenario

    def snapshot(self, s):
        """Every file of the project but git's own, with its content, mode and modification time."""
        files = {}
        for directory, dirs, names in os.walk(s.work):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                path = os.path.join(directory, name)
                info = os.stat(path)
                with open(path, "rb") as f:
                    files[os.path.relpath(path, s.work)] = (f.read(), info.st_mode, info.st_mtime_ns)
        return files

    def test_setting_up_a_set_up_project_again_changes_nothing(self):
        s = self.scenario()
        s.release()
        self.assertEqual(s.setup().status, 0)
        before = self.snapshot(s)
        mutations = s.events()

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(result.output, f"ralph: {s.work} is already set up for ralph {VERSION}; nothing changed\n")
        self.assertEqual(self.snapshot(s), before)
        self.assertEqual(s.events(), mutations)

    def test_setup_again_keeps_the_maintainers_configuration_rules_and_pin(self):
        s = self.scenario()
        s.release()
        self.assertEqual(s.setup().status, 0)
        s.write(".ralph/config", "verify = make check\n")
        s.write(".ralph/rules/implement.md", "Use tabs.\n")
        s.write(".ralph/rules/review.md", "Be kind.\n")
        s.write(".ralph/pin", "v0.0.9\n")

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.read(".ralph/config"), "verify = make check\n")
        self.assertEqual(s.read(".ralph/rules/implement.md"), "Use tabs.\n")
        self.assertEqual(s.read(".ralph/rules/review.md"), "Be kind.\n")
        self.assertEqual(s.read(".ralph/pin"), "v0.0.9\n")

    def test_setup_again_restores_and_refreshes_what_is_ralphs(self):
        s = self.scenario()
        s.release()
        self.assertEqual(s.setup().status, 0)
        fresh = {path: s.read(path) for path in ("ralph", ".ralph/.gitignore", "docs/agents/issue-tracker.md")}
        claude_md = s.read("CLAUDE.md")
        os.remove(os.path.join(s.work, "ralph"))
        os.remove(os.path.join(s.work, ".ralph", ".gitignore"))
        s.write("docs/agents/issue-tracker.md", s.read("docs/agents/issue-tracker.md") + "Stale.\n")
        s.write("CLAUDE.md", "# Widgets\n\n" + claude_md.replace("./ralph help", "ralph --help") + "\nMore.\n")

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        for path, content in fresh.items():
            self.assertEqual(s.read(path), content, path)
        self.assertTrue(os.access(os.path.join(s.work, "ralph"), os.X_OK))
        self.assertEqual(s.read("CLAUDE.md"), "# Widgets\n\n" + claude_md + "\nMore.\n")
        self.assertIn("  created ralph\n", result.output)
        self.assertIn("  refreshed CLAUDE.md\n", result.output)

    def test_an_existing_label_is_left_as_it_is(self):
        s = self.scenario()
        s.release()
        s.add_label("ready-for-agent")

        result = s.setup()

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), [])
        self.assertNotIn("label", result.output)

    def test_a_broken_ralph_section_stops_setup_before_it_changes_anything(self):
        s = self.scenario()
        s.release()
        s.commit_file("CLAUDE.md", "# Widgets\n\n<!-- ralph:begin -->\nhalf a section\n", "Broken section")

        result = s.setup()

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: CLAUDE.md has a broken ralph section", result.output)
        self.assertEqual(s.status(), "")
        self.assertEqual(s.events(), [])

    def test_a_file_named_like_the_wrapper_stops_setup_before_it_changes_anything(self):
        s = self.scenario()
        s.release()
        s.commit_file("ralph", "#!/bin/sh\necho mine\n", "Our own ralph")

        result = s.setup()

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(f"ralph: {s.work}/ralph exists and is not ralph's wrapper", result.output)
        self.assertEqual(s.status(), "")
        self.assertEqual(s.events(), [])


class ExplicitPin(ScenarioTestCase):
    """`setup --pin <tag>`: the maintainer names the pin, as when a project is set up ahead of its release."""

    scenario = Setup.scenario

    def test_an_explicit_pin_to_an_unpublished_tag_is_written_with_a_warning(self):
        s = self.scenario()

        result = s.setup("--pin", "v0.2.0")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.read(".ralph/pin"), "v0.2.0\n")
        self.assertIn(
            f"ralph: warning: v0.2.0 is not released in file://{s.clone} yet, so the wrapper cannot run until "
            "the tag is pushed there",
            result.output,
        )

    def test_an_explicit_pin_to_a_released_tag_needs_no_warning_and_runs(self):
        s = self.scenario()
        s.release("v0.3.0")
        s.git_in(s.clone, "commit", "-q", "--allow-empty", "-m", "Work after the release")

        result = s.setup("--pin", "v0.3.0")

        self.assertEqual(result.status, 0, result.output)
        self.assertNotIn("warning", result.output)
        self.assertEqual(s.read(".ralph/pin"), "v0.3.0\n")
        self.assertEqual(s.wrapper("help").status, 0)

    def test_an_explicit_pin_that_is_not_a_version_name_sets_nothing_up(self):
        s = self.scenario()

        result = s.setup("--pin", "../v1")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("ralph: --pin needs a version name such as v0.1.0, not '../v1'", result.output)
        self.assertEqual(s.status(), "")
        self.assertEqual(s.events(), [])

    def test_an_explicit_pin_never_moves_the_pin_a_project_has(self):
        s = self.scenario()
        s.commit_file(".ralph/pin", "v0.1.0\n", "Pin ralph")

        result = s.setup("--pin", "v0.2.0")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(
            "ralph: the project is pinned to v0.1.0 and set-up never moves a pin; move it with "
            "`./ralph upgrade v0.2.0`, or rerun without --pin",
            result.output,
        )
        self.assertEqual(s.read(".ralph/pin"), "v0.1.0\n")
        self.assertEqual(s.status(), "")
