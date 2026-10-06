"""`ralph sync-skills`: the maintainer regenerates the bundled skills from a local skills directory.

Each test copies ralph into a scratch clone, because the command writes the
plugin into the clone it runs from, and builds a fixture skills directory in a
scratch HOME laid out like the maintainer's: `~/.claude/skills/<name>` linking
to skills installed under `~/.agents/skills`, next to the installer's lock file.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.harness import ROOT, Result

BUNDLED = ("implement", "tdd", "code-review", "to-tickets")

UPSTREAM = "https://github.com/mattpocock/skills.git"


def _skill_md(name, body):
    return f"---\nname: {name}\ndescription: The {name} skill.\n---\n\n{body}"


class Clone:
    def __init__(self, root):
        self.root = root
        self.clone = os.path.join(root, "ralph")
        self.home = os.path.join(root, "home")
        self.installed = os.path.join(self.home, ".agents", "skills")
        self.skills = os.path.join(self.home, ".claude", "skills")
        for part in ("bin", "src"):
            shutil.copytree(
                os.path.join(ROOT, part), os.path.join(self.clone, part), ignore=shutil.ignore_patterns("__pycache__")
            )
        os.makedirs(self.installed)
        os.makedirs(self.skills)
        self.lock = {"version": 3, "skills": {}}
        self._save_lock()

    def skill(self, name, body="Do the thing.\n", files=None, upstream=True):
        """Installs a skill the way the maintainer's installer does: a real directory linked from ~/.claude/skills."""
        directory = os.path.join(self.installed, name)
        os.makedirs(directory)
        self._write(os.path.join(directory, "SKILL.md"), _skill_md(name, body))
        for path, content in (files or {}).items():
            self._write(os.path.join(directory, path), content)
        os.symlink(os.path.join("..", "..", ".agents", "skills", name), os.path.join(self.skills, name))
        if upstream:
            self.lock["skills"][name] = {
                "source": "mattpocock/skills",
                "sourceType": "github",
                "sourceUrl": UPSTREAM,
                "skillPath": f"skills/engineering/{name}/SKILL.md",
                "skillFolderHash": f"hash-of-{name}",
            }
            self._save_lock()

    def all_bundled(self, **bodies):
        for name in BUNDLED:
            self.skill(name, bodies.get(name.replace("-", "_"), f"The {name} body.\n"))

    def _save_lock(self):
        self._write(os.path.join(self.home, ".agents", ".skill-lock.json"), json.dumps(self.lock))

    @staticmethod
    def _write(path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def plugin(self, *path):
        return os.path.join(self.clone, "plugin", *path)

    def read(self, *path):
        with open(self.plugin(*path)) as f:
            return f.read()

    def files(self):
        """Every file of the plugin, relative to it."""
        found = []
        for directory, _, names in os.walk(self.plugin()):
            found += [os.path.relpath(os.path.join(directory, n), self.plugin()) for n in names]
        return sorted(found)

    def ralph(self, *args):
        proc = subprocess.run(
            (sys.executable, os.path.join(self.clone, "bin", "ralph")) + args,
            cwd=self.root,
            env={"PATH": os.environ.get("PATH", ""), "HOME": self.home, "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        return Result(proc.returncode, proc.stdout)


class SyncTestCase(unittest.TestCase):
    def clone(self):
        root = tempfile.mkdtemp(prefix="ralph-sync-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return Clone(os.path.realpath(root))

    def sync(self, c, *args):
        result = c.ralph("sync-skills", *args)
        self.assertEqual(result.status, 0, result.output)
        return result


class Overwrites(SyncTestCase):
    def test_the_bundled_skills_and_their_supporting_files_replace_the_previous_copies(self):
        c = self.clone()
        c.skill("implement")
        c.skill("tdd", "See tests.md.\n", files={"tests.md": "old tests\n", "mocking.md": "old mocking\n"})
        c.skill("code-review")
        c.skill("to-tickets")
        c.skill("unrelated")
        self.sync(c)

        shutil.rmtree(os.path.join(c.installed, "tdd"))
        c._write(os.path.join(c.installed, "tdd", "SKILL.md"), _skill_md("tdd", "See tests.md, version two.\n"))
        c._write(os.path.join(c.installed, "tdd", "tests.md"), "new tests\n")
        c._write(os.path.join(c.installed, "tdd", "agents", "openai.yaml"), "interface: {}\n")
        self.sync(c)

        skills = [f for f in c.files() if f.startswith("skills/")]
        self.assertEqual(
            skills,
            [
                "skills/code-review/SKILL.md",
                "skills/implement/SKILL.md",
                "skills/tdd/SKILL.md",
                "skills/tdd/agents/openai.yaml",
                "skills/tdd/tests.md",
                "skills/to-tickets/SKILL.md",
            ],
        )
        self.assertEqual(c.read("skills", "tdd", "tests.md"), "new tests\n")
        self.assertIn("See tests.md, version two.", c.read("skills", "tdd", "SKILL.md"))

    def test_the_plugin_is_named_ralph(self):
        c = self.clone()
        c.all_bundled()
        self.sync(c)

        self.assertEqual(json.loads(c.read(".claude-plugin", "plugin.json"))["name"], "ralph")

    def test_a_missing_bundled_skill_stops_without_touching_the_plugin(self):
        c = self.clone()
        c.all_bundled()
        self.sync(c)
        before = {f: c.read(f) for f in c.files()}
        shutil.rmtree(os.path.join(c.installed, "to-tickets"))

        result = c.ralph("sync-skills")

        self.assertEqual(result.status, 1, result.output)
        self.assertIn("to-tickets", result.output)
        self.assertEqual({f: c.read(f) for f in c.files()}, before)


class RepointsReferences(SyncTestCase):
    def test_references_between_bundled_skills_become_ralph_names_and_other_text_is_untouched(self):
        c = self.clone()
        c.skill(
            "implement",
            "Implement the work, tdd style, then code-review it.\n"
            "Use /tdd where possible.\n"
            "Once done, use /code-review to review the work.\n"
            "Files live in skills/tdd/ and docs/implement.md.\n",
        )
        c.skill(
            "tdd",
            "Refactoring belongs to the review stage (see the `code-review` skill).\n"
            'Then call the Skill tool with "to-tickets".\n'
            "See [tests.md](tests.md).\n",
            files={"tests.md": "Run /implement first.\n\n```js\nfetch(`/users/1`);\n```\n"},
        )
        c.skill("code-review")
        c.skill("to-tickets")

        self.sync(c)

        self.assertEqual(
            c.read("skills", "implement", "SKILL.md"),
            _skill_md(
                "implement",
                "Implement the work, tdd style, then code-review it.\n"
                "Use /ralph:tdd where possible.\n"
                "Once done, use /ralph:code-review to review the work.\n"
                "Files live in skills/tdd/ and docs/implement.md.\n",
            ),
        )
        self.assertEqual(
            c.read("skills", "tdd", "SKILL.md"),
            _skill_md(
                "tdd",
                "Refactoring belongs to the review stage (see the `ralph:code-review` skill).\n"
                'Then call the Skill tool with "ralph:to-tickets".\n'
                "See [tests.md](tests.md).\n",
            ),
        )
        self.assertEqual(
            c.read("skills", "tdd", "tests.md"), "Run /ralph:implement first.\n\n```js\nfetch(`/users/1`);\n```\n"
        )


class ReportsUnbundledReferences(SyncTestCase):
    def test_a_reference_to_a_skill_that_is_not_bundled_is_reported_and_left_alone(self):
        c = self.clone()
        c.skill("implement", "Use /tdd, then /grilling.\n")
        c.skill("tdd", 'Call the Skill tool with "codebase-design".\n', files={"tests.md": "Try `grilling`.\n"})
        c.skill("code-review", "If the tracker is missing, run `/setup-matt-pocock-skills`.\n")
        c.skill("to-tickets", "Fetch `/users/1` from skills/grilling/ and grill the user.\n")
        for name in ("grilling", "codebase-design", "setup-matt-pocock-skills"):
            c.skill(name)

        result = self.sync(c)

        self.assertIn(
            "ralph: bundled skills refer to skills that are not bundled:\n"
            "  code-review/SKILL.md: /setup-matt-pocock-skills\n"
            "  implement/SKILL.md: /grilling\n"
            "  tdd/SKILL.md: codebase-design\n"
            "  tdd/tests.md: grilling\n",
            result.output,
        )
        self.assertEqual(
            c.read("skills", "implement", "SKILL.md"), _skill_md("implement", "Use /ralph:tdd, then /grilling.\n")
        )

    def test_nothing_is_reported_when_every_reference_is_bundled(self):
        c = self.clone()
        c.all_bundled(implement="Use /tdd.\n")
        c.skill("grilling")

        result = self.sync(c)

        self.assertNotIn("not bundled", result.output)


class RecordsOrigins(SyncTestCase):
    def test_each_bundled_skill_records_where_it_was_copied_from_and_its_upstream(self):
        c = self.clone()
        c.skill("implement")
        c.skill("tdd")
        c.skill("code-review")
        c.skill("to-tickets", upstream=False)

        self.sync(c)

        readme = c.read("README.md")
        self.assertIn("never edit", readme)
        self.assertIn(
            "- `implement`: copied from `~/.claude/skills/implement`, "
            f"upstream {UPSTREAM} `skills/engineering/implement` at `hash-of-implement`\n",
            readme,
        )
        self.assertIn(
            "- `code-review`: copied from `~/.claude/skills/code-review`, "
            f"upstream {UPSTREAM} `skills/engineering/code-review` at `hash-of-code-review`\n",
            readme,
        )
        self.assertIn("- `to-tickets`: copied from `~/.claude/skills/to-tickets`, no upstream recorded\n", readme)

    def test_a_skills_directory_given_on_the_command_line_is_recorded_as_given(self):
        c = self.clone()
        c.all_bundled()

        self.sync(c, os.path.join(c.home, ".agents", "skills"))

        self.assertIn(f"- `tdd`: copied from `{c.installed}/tdd`, upstream {UPSTREAM}", c.read("README.md"))

    def test_the_upstream_mit_license_notice_is_carried(self):
        c = self.clone()
        c.all_bundled()

        self.sync(c)

        notice = c.read("LICENSE")
        self.assertTrue(notice.startswith("MIT License\n\nCopyright (c) 2026 Matt Pocock\n"), notice)
        self.assertIn("The above copyright notice and this permission notice shall be included", notice)


if __name__ == "__main__":
    unittest.main()
