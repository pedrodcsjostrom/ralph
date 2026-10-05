"""Upgrade, run as a runner runs it: through the project's wrapper, against a
local git repository standing in for the public ralph repository.

Every release in that repository is a copy of this checkout's ralph, so the
pinned version the wrapper hands over to is the code under test.
"""

import os
import shutil
import tempfile
import unittest

from tests.test_wrapper import ROOT, WrapperWorld


class UpgradeWorld(WrapperWorld):
    def __init__(self, root):
        super().__init__(root)
        self.git(self.project, "init", "-q")
        shutil.copytree(os.path.join(ROOT, "bin"), os.path.join(self.public, "bin"))
        shutil.copytree(
            os.path.join(ROOT, "src"),
            os.path.join(self.public, "src"),
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.git(self.public, "add", "-A")
        self.git(self.public, "commit", "-q", "-m", "ralph")

    def release(self, *versions):
        for version in versions:
            self.git(self.public, "tag", version)

    def pinned(self):
        with open(os.path.join(self.project, ".ralph", "pin")) as f:
            return f.read()


class UpgradeTest(unittest.TestCase):
    def world(self):
        root = tempfile.mkdtemp(prefix="ralph-upgrade-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return UpgradeWorld(os.path.realpath(root))

    def test_upgrade_moves_the_pin_to_the_newest_version(self):
        w = self.world()
        w.release("v0.2.0", "v0.9.0", "v0.10.0")
        w.pin("v0.2.0")

        result = w.wrapper("upgrade")

        self.assertEqual(result.status, 0, result.output)
        self.assertTrue(result.output.endswith("ralph: moved the pin from v0.2.0 to v0.10.0\n"), result.output)
        self.assertEqual(w.pinned(), "v0.10.0\n")

    def test_upgrade_to_a_named_version_moves_the_pin_to_it(self):
        w = self.world()
        w.release("v0.2.0", "v0.9.0", "v0.10.0")
        w.pin("v0.2.0")

        result = w.wrapper("upgrade", "v0.9.0")

        self.assertEqual(result.status, 0, result.output)
        self.assertTrue(result.output.endswith("ralph: moved the pin from v0.2.0 to v0.9.0\n"), result.output)
        self.assertEqual(w.pinned(), "v0.9.0\n")

    def test_upgrade_to_a_version_that_does_not_exist_fails_and_leaves_the_pin(self):
        w = self.world()
        w.release("v0.2.0", "v0.9.0")
        w.pin("v0.2.0")

        result = w.wrapper("upgrade", "v0.10.0")

        self.assertEqual(result.status, 1, result.output)
        self.assertTrue(
            result.output.endswith(f"ralph: there is no version v0.10.0 in {w.repository}; the pin stays at v0.2.0\n"),
            result.output,
        )
        self.assertEqual(w.pinned(), "v0.2.0\n")

    def test_upgrade_when_already_on_the_newest_version_changes_nothing(self):
        w = self.world()
        w.release("v0.2.0", "v0.10.0")
        w.pin("v0.10.0")

        result = w.wrapper("upgrade")

        self.assertEqual(result.status, 0, result.output)
        self.assertTrue(
            result.output.endswith("ralph: already on the newest version, v0.10.0; nothing changed\n"), result.output
        )
        self.assertEqual(w.pinned(), "v0.10.0\n")

    def test_upgrade_to_the_pinned_version_changes_nothing(self):
        w = self.world()
        w.release("v0.2.0", "v0.10.0")
        w.pin("v0.2.0")

        result = w.wrapper("upgrade", "v0.2.0")

        self.assertEqual(result.status, 0, result.output)
        self.assertTrue(result.output.endswith("ralph: already on v0.2.0; nothing changed\n"), result.output)
        self.assertEqual(w.pinned(), "v0.2.0\n")

    def test_upgrade_from_a_subdirectory_moves_the_projects_pin(self):
        w = self.world()
        w.release("v0.2.0", "v0.10.0")
        w.pin("v0.2.0")
        subdir = os.path.join(w.project, "src")
        os.makedirs(subdir)

        result = w.wrapper("upgrade", cwd=subdir)

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(w.pinned(), "v0.10.0\n")
        self.assertFalse(os.path.exists(os.path.join(subdir, ".ralph")))

    def test_upgrade_run_from_another_repository_moves_the_wrappers_projects_pin(self):
        w = self.world()
        w.release("v0.2.0", "v0.10.0")
        w.pin("v0.2.0")
        elsewhere = os.path.join(w.root, "elsewhere")
        os.makedirs(os.path.join(elsewhere, ".ralph"))
        w.git(elsewhere, "init", "-q")
        with open(os.path.join(elsewhere, ".ralph", "pin"), "w") as f:
            f.write("v0.2.0\n")

        result = w.wrapper("upgrade", cwd=elsewhere)

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(w.pinned(), "v0.10.0\n")
        with open(os.path.join(elsewhere, ".ralph", "pin")) as f:
            self.assertEqual(f.read(), "v0.2.0\n")

    def test_upgrade_fails_and_leaves_the_pin_when_the_repository_cannot_be_reached(self):
        w = self.world()
        w.release("v0.2.0", "v0.10.0")
        w.pin("v0.2.0")
        self.assertEqual(w.wrapper("upgrade", "v0.2.0").status, 0)  # v0.2.0 is now cached
        unreachable = "file://" + os.path.join(w.root, "unreachable")

        result = w.wrapper("upgrade", RALPH_REPOSITORY=unreachable)

        self.assertEqual(result.status, 1, result.output)
        self.assertIn(f"ralph: could not list the versions in {unreachable}:\n", result.output)
        self.assertEqual(w.pinned(), "v0.2.0\n")


if __name__ == "__main__":
    unittest.main()
