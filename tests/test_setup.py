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
        for part in ("bin", "ralph", "plugin", "wrapper"):
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
