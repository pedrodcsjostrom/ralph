"""The wrapper, run as a runner runs it: from a project, against a local git
repository standing in for the public ralph repository.

The released ralph in that repository is a stand-in `bin/ralph` that reports
its version, its arguments and the directory it runs in, and exits with the
status it is asked for, so hand-over is observable without the real loop.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER = os.path.join(ROOT, "wrapper", "ralph")

STAND_IN = """\
import os
import sys

print("ralph %s" % VERSION)
print("args %r" % (sys.argv[1:],))
print("cwd %s" % os.getcwd())
sys.exit(int(os.environ.get("STAND_IN_EXIT", "0")))
"""


class Result:
    def __init__(self, status, output):
        self.status = status
        self.output = output

    def __repr__(self):
        return f"Result(status={self.status!r}, output={self.output!r})"


class WrapperWorld:
    """A public ralph repository, a project that commits the wrapper, and a
    per-user cache, all in a scratch directory."""

    def __init__(self, root):
        self.root = root
        self.public = os.path.join(root, "public")
        self.project = os.path.join(root, "project")
        self.home = os.path.join(root, "home")
        self.cache = os.path.join(root, "cache")
        for path in (self.public, self.project, self.home):
            os.makedirs(path)
        self.gitconfig = os.path.join(root, "gitconfig")
        with open(self.gitconfig, "w") as f:
            f.write("[user]\n\tname = ralph\n\temail = ralph@example.com\n[init]\n\tdefaultBranch = main\n")
        # A URL, so the fetch goes through git's transport as it does for the public one.
        self.repository = "file://" + self.public
        self.git(self.public, "init", "-q")
        shutil.copy(WRAPPER, os.path.join(self.project, "ralph"))

    def env(self, **extra):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": self.home,
            "GIT_CONFIG_GLOBAL": self.gitconfig,
            "GIT_CONFIG_NOSYSTEM": "1",
            "RALPH_REPOSITORY": self.repository,
            "XDG_CACHE_HOME": self.cache,
        }
        env.update(extra)
        return env

    def git(self, cwd, *args):
        proc = subprocess.run(["git", *args], cwd=cwd, env=self.env(), check=True, capture_output=True, text=True)
        return proc.stdout.strip()

    def release(self, version):
        """Commits a stand-in ralph that reports `version` and tags it."""
        bin_dir = os.path.join(self.public, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        with open(os.path.join(bin_dir, "ralph"), "w") as f:
            f.write(f"VERSION = {version!r}\n" + STAND_IN)
        self.git(self.public, "add", "-A")
        self.git(self.public, "commit", "-q", "-m", "Release " + version)
        self.git(self.public, "tag", version)

    def pin(self, version):
        os.makedirs(os.path.join(self.project, ".ralph"), exist_ok=True)
        with open(os.path.join(self.project, ".ralph", "pin"), "w") as f:
            f.write(version + "\n")

    def wrapper(self, *args, cwd=None, **env):
        proc = subprocess.run(
            [sys.executable, os.path.join(self.project, "ralph"), *args],
            cwd=cwd or self.project,
            env=self.env(**env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return Result(proc.returncode, proc.stdout)

    def cached(self):
        """The entries of the per-user cache's ralph directory."""
        path = os.path.join(self.cache, "ralph")
        return sorted(os.listdir(path)) if os.path.isdir(path) else []


class WrapperTest(unittest.TestCase):
    def world(self):
        root = tempfile.mkdtemp(prefix="ralph-wrapper-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return WrapperWorld(os.path.realpath(root))

    def test_first_run_fetches_the_pinned_version_and_runs_it(self):
        w = self.world()
        w.release("v1")
        w.release("v2")
        w.pin("v1")

        result = w.wrapper("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertIn("ralph v1\n", result.output)
        self.assertIn("args ['run', '1']\n", result.output)
        self.assertEqual(w.cached(), ["v1"])

    def test_a_cached_version_is_reused_without_the_remote(self):
        w = self.world()
        w.release("v1")
        w.pin("v1")
        self.assertEqual(w.wrapper().status, 0)
        shutil.rmtree(w.public)

        result = w.wrapper("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertIn("ralph v1\n", result.output)
        self.assertNotIn("fetching", result.output)

    def test_arguments_exit_status_and_directory_pass_through(self):
        w = self.world()
        w.release("v1")
        w.pin("v1")
        subdir = os.path.join(w.project, "src")
        os.makedirs(subdir)

        result = w.wrapper("run", "#1", "--flag", "two words", cwd=subdir, STAND_IN_EXIT="3")

        self.assertEqual(result.status, 3, result.output)
        self.assertIn("args ['run', '#1', '--flag', 'two words']\n", result.output)
        self.assertIn(f"cwd {subdir}\n", result.output)

    def test_a_pin_naming_a_missing_version_fails_and_caches_nothing(self):
        w = self.world()
        w.release("v1")
        w.pin("v9")

        result = w.wrapper("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(
            result.output,
            "ralph: fetching ralph v9\n"
            f"ralph: the pinned version v9 does not exist in {w.repository} (pin: .ralph/pin)\n",
        )
        self.assertEqual(w.cached(), [])

    def test_a_failed_fetch_fails_and_caches_nothing(self):
        w = self.world()
        w.release("v1")
        w.pin("v1")
        w.repository = "file://" + os.path.join(w.root, "unreachable")

        result = w.wrapper("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertTrue(result.output.startswith("ralph: fetching ralph v1\n"), result.output)
        self.assertIn(f"ralph: could not fetch ralph v1 from {w.repository}:\n", result.output)
        self.assertEqual(w.cached(), [])

    def test_a_fetch_that_breaks_off_halfway_caches_nothing(self):
        w = self.world()
        w.release("v1")
        w.pin("v1")
        # The tag is advertised, but the repository has lost an object it needs.
        blob = w.git(w.public, "rev-parse", "v1:bin/ralph")
        os.remove(os.path.join(w.public, ".git", "objects", blob[:2], blob[2:]))

        result = w.wrapper()

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(f"ralph: could not fetch ralph v1 from {w.repository}:\n", result.output)
        self.assertEqual(w.cached(), [])

    def test_a_project_without_a_pin_is_refused(self):
        w = self.world()
        w.release("v1")

        result = w.wrapper("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(result.output, "ralph: no pin at .ralph/pin; this project is not set up to run ralph\n")
        self.assertEqual(w.cached(), [])

    def test_a_pin_that_is_not_a_version_name_is_refused(self):
        w = self.world()
        w.release("v1")
        w.pin("../v1")

        result = w.wrapper("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(result.output, "ralph: the pin in .ralph/pin is not a version name: '../v1'\n")
        self.assertEqual(w.cached(), [])

    def test_the_cache_location_can_be_overridden(self):
        w = self.world()
        w.release("v1")
        w.pin("v1")
        elsewhere = os.path.join(w.root, "elsewhere")

        result = w.wrapper(RALPH_CACHE=elsewhere)

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(os.listdir(elsewhere), ["v1"])
        self.assertEqual(w.cached(), [])

    def test_the_first_run_says_it_is_fetching(self):
        w = self.world()
        w.release("v1")
        w.pin("v1")

        result = w.wrapper()

        self.assertTrue(result.output.startswith("ralph: fetching ralph v1\n"), result.output)


if __name__ == "__main__":
    unittest.main()
