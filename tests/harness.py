"""The command-line test seam.

A Scenario is a scratch world for one test: a real git repository on `main`,
a fake tracker holding one spec, a fake agent, and a PATH that holds only the
fakes and the real git. Tests run the real entry point (`bin/ralph`) in it and
assert on what a runner could observe: exit status, terminal output, commits,
and the calls the fakes recorded.

    class RunTest(ScenarioTestCase):
        def test_something(self):
            s = self.scenario()
            s.ticket(2)
            s.ticket(3, blocked_by=[2])
            result = s.ralph("run", "1")
            self.assertEqual(result.status, 0, result.output)
            self.assertEqual(s.events(), ["agent #2", "close #2", "agent #3", "close #3"])
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import terminal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RALPH = os.path.join(ROOT, "bin", "ralph")
FAKES = os.path.join(ROOT, "tests", "fakes")

SPEC = 1
SPEC_TITLE = "Spec: Widget Sorting!"
REPO = "acme/widgets"


class Result:
    def __init__(self, status, output):
        self.status = status
        self.output = output

    def __repr__(self):
        return f"Result(status={self.status!r}, output={self.output!r})"


class Scenario:
    def __init__(self, root):
        self.root = root
        self.entry_point = RALPH
        self.work = os.path.join(root, "repo")
        self.fake = os.path.join(root, "fake")
        self.bin = os.path.join(root, "bin")
        self.home = os.path.join(root, "home")
        for path in (self.work, self.fake, self.bin, self.home):
            os.makedirs(path)

        self.gitconfig = os.path.join(root, "gitconfig")
        with open(self.gitconfig, "w") as f:
            f.write("[user]\n\tname = ralph\n\temail = ralph@example.com\n[init]\n\tdefaultBranch = main\n")

        self._write_state(
            "tracker",
            {
                "repo": REPO,
                "logged_in": True,
                "labels": ["bug", "enhancement"],
                "issues": {str(SPEC): {"title": SPEC_TITLE, "body": "The spec.", "sub_issues": []}},
            },
        )
        self._write_state("agent", {"logged_in": True, "behaviours": {}})
        open(os.path.join(self.fake, "calls.jsonl"), "w").close()

        self.install_tool("git", shutil.which("git"))
        self.install_fake("gh")
        self.install_fake("claude")

        self.git("init", "-q", "-b", "main")
        self.commit_file("README.md", "widgets\n", "Initial commit")

    # The world outside the repository.

    def install_fake(self, name):
        """Puts tests/fakes/<name>.py on the path as `name`, run by this Python."""
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\nexec '{}' '{}' \"$@\"\n".format(sys.executable, os.path.join(FAKES, name + ".py")))
        os.chmod(path, 0o755)

    def install_tool(self, name, target):
        os.symlink(os.path.realpath(target), os.path.join(self.bin, name))

    def remove_tool(self, name):
        os.remove(os.path.join(self.bin, name))

    def env(self, **extra):
        env = {
            "PATH": self.bin,
            "HOME": self.home,
            "RALPH_FAKE": self.fake,
            "GIT_CONFIG_GLOBAL": self.gitconfig,
            "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C.UTF-8",
            "TMPDIR": self.root,
        }
        env.update(extra)
        return env

    # The fake tracker.

    def ticket(
        self, number, title=None, labels=("ready-for-agent",), blocked_by=(), state="open", body="", comments=()
    ):
        """Adds a sub-issue to the spec."""
        tracker = self._read_state("tracker")
        tracker["issues"][str(number)] = {
            "title": title or f"Ticket {number}",
            "state": state,
            "labels": list(labels),
            "blocked_by": list(blocked_by),
            "body": body,
            "comments": list(comments),
        }
        tracker["issues"][str(SPEC)]["sub_issues"].append(number)
        self._write_state("tracker", tracker)

    def tracker_misshapes(self, number):
        """Makes the tracker answer with an empty object when asked about issue number, as if GitHub changed shape."""
        tracker = self._read_state("tracker")
        tracker["issues"][str(number)]["misshapen"] = True
        self._write_state("tracker", tracker)

    def tracker_logged_in(self, logged_in):
        tracker = self._read_state("tracker")
        tracker["logged_in"] = logged_in
        self._write_state("tracker", tracker)

    def tracker_delays(self, seconds, only=None):
        """Makes every call to the tracker take seconds, as a slow network does; given only, such as "pr create",
        just the calls of that command."""
        tracker = self._read_state("tracker")
        tracker["delay"] = seconds
        tracker["delay_only"] = only
        self._write_state("tracker", tracker)

    def add_label(self, name):
        tracker = self._read_state("tracker")
        tracker["labels"].append(name)
        self._write_state("tracker", tracker)

    def labels(self):
        """The names of the repository's labels on the fake tracker."""
        return self._read_state("tracker")["labels"]

    def issue(self, number):
        """The tracker's current view of an issue."""
        return self._read_state("tracker")["issues"][str(number)]

    # The fake agent.

    def agent_does(self, ticket, *behaviours):
        """Queues what the agent does on each attempt at a ticket (see tests/fakes/claude.py)."""
        agent = self._read_state("agent")
        agent["behaviours"][str(ticket)] = list(behaviours)
        self._write_state("agent", agent)

    def agent_pauses(self, seconds):
        """Makes every headless run go silent for seconds in the middle of a tool call."""
        agent = self._read_state("agent")
        agent["pause"] = seconds
        self._write_state("agent", agent)

    def review_finds(self, round_, *findings):
        """What review round round_ writes to its findings file: dicts with title, what_to_build and so on."""
        self.review_writes(round_, json.dumps(list(findings)))

    def review_writes(self, round_, text, also=None):
        """Review round round_ writes text, verbatim, as its findings; None writes no findings file at all.

        also is a misbehaviour on top: "dirty", "commit" or "switch-branch" (see tests/fakes/claude.py).
        """
        agent = self._read_state("agent")
        agent.setdefault("reviews", {})[str(round_)] = {"findings": text, "also": also}
        self._write_state("agent", agent)

    def split_creates(self, *titles, status=0):
        """What a session splitting the spec does: opens tickets titled titles, then exits with status."""
        agent = self._read_state("agent")
        agent.setdefault("splits", {})[str(SPEC)] = {"tickets": list(titles), "status": status}
        self._write_state("agent", agent)

    def agent_ignores_settings(self):
        """The agent's CLI silently drops the settings it is launched with, as Claude Code does with invalid ones."""
        agent = self._read_state("agent")
        agent["ignores_settings"] = True
        self._write_state("agent", agent)

    def agent_logged_in(self, logged_in):
        agent = self._read_state("agent")
        agent["logged_in"] = logged_in
        self._write_state("agent", agent)

    # The fakes' state files are the only copy: fakes change them during a
    # run, so the harness always reads them afresh before changing them.

    def _read_state(self, name):
        with open(os.path.join(self.fake, name + ".json")) as f:
            return json.load(f)

    def _write_state(self, name, state):
        with open(os.path.join(self.fake, name + ".json"), "w") as f:
            json.dump(state, f, indent=2)

    # What the fakes saw.

    def calls(self, tool=None):
        """Every recorded call, oldest first, optionally only those of one tool."""
        with open(os.path.join(self.fake, "calls.jsonl")) as f:
            calls = [json.loads(line) for line in f if line.strip()]
        return [c for c in calls if tool is None or c["tool"] == tool]

    def events(self):
        """Agent runs and tracker mutations, in order, as short strings like "agent #3", "split #1", "close #3" and
        "label ready-for-agent"."""
        events = []
        for call in self.calls():
            if call["tool"] == "claude" and "ticket" in call:
                events.append(f"agent #{call['ticket']}")
            elif call["tool"] == "claude" and "split" in call:
                events.append(f"split #{call['split']}")
            elif call["tool"] == "claude" and "review" in call:
                events.append(f"review {call['review']}")
            elif call["tool"] == "gh" and call.get("mutation") == "label":
                events.append(f"label {call['label']}")
            elif call["tool"] == "gh" and "mutation" in call:
                events.append(f"{call['mutation']} #{call['ticket']}")
        return events

    def prompts(self):
        return [c["prompt"] for c in self.calls("claude") if "prompt" in c]

    # The repository.

    def git(self, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=self.work,
            env=self.env(),
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def commit_file(self, path, content, message):
        self.write(path, content)
        self.git("add", path)
        self.git("commit", "-q", "-m", message)

    def write(self, path, content):
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    def branch(self):
        return self.git("branch", "--show-current")

    def log(self, revisions):
        """Subjects of the commits in a revision range, oldest first."""
        out = self.git("log", "--reverse", "--format=%s", revisions)
        return out.splitlines() if out else []

    def status(self):
        return self.git("status", "--porcelain")

    def add_remote(self, name="origin"):
        """Creates a local bare repository and adds it to the repository as remote name."""
        path = os.path.join(self.root, name + ".git")
        subprocess.run(("git", "init", "-q", "--bare", path), env=self.env(), check=True)
        self.git("remote", "add", name, path)
        return path

    def remote_delays(self, seconds, name="origin"):
        """Makes every push to the remote take seconds, as a slow network does."""
        hook = os.path.join(self.root, name + ".git", "hooks", "pre-receive")
        with open(hook, "w") as f:
            f.write(f"#!{sys.executable}\nimport sys, time\nsys.stdin.read()\ntime.sleep({seconds!r})\n")
        os.chmod(hook, 0o755)

    def remote_branches(self, name="origin"):
        """The branches of the remote and the commits they point at, as {branch: sha}."""
        out = self.git("ls-remote", "--heads", name)
        prefix = "refs/heads/"
        return {ref[len(prefix) :]: sha for sha, ref in (line.split("\t") for line in out.splitlines())}

    def pull_requests(self):
        """The pull requests opened on the fake tracker, oldest first."""
        return self._read_state("tracker").get("pull_requests", [])

    def run_dirs(self):
        """The run directories, oldest first."""
        runs = os.path.join(self.work, ".ralph", "runs")
        if not os.path.isdir(runs):
            return []
        names = [d for d in os.listdir(runs) if os.path.isdir(os.path.join(runs, d))]

        def started(name):
            # YYYYmmdd-HHMMSS, then -N for the Nth run started in the same second.
            day, _, rest = name.partition("-")
            second, _, n = rest.partition("-")
            return day, second, int(n or 1)

        return [os.path.join(runs, d) for d in sorted(names, key=started)]

    # Ralph.

    def use_ralph_copy(self):
        """Runs a scratch copy of ralph from now on, so a test can break it. Returns the copy's plugin directory."""
        copy = os.path.join(self.root, "ralph")
        for part in ("bin", "src", "plugin"):
            shutil.copytree(
                os.path.join(ROOT, part), os.path.join(copy, part), ignore=shutil.ignore_patterns("__pycache__")
            )
        self.entry_point = os.path.join(copy, "bin", "ralph")
        return os.path.join(copy, "plugin")

    def ralph(self, *args, **env):
        proc = subprocess.run(
            (sys.executable, self.entry_point) + args,
            cwd=self.work,
            env=self.env(**env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        return Result(proc.returncode, proc.stdout)

    def ralph_on_terminal(self, *args, columns=terminal.COLUMNS, interrupt_when=None, **env):
        """Runs ralph on a pseudo-terminal (see tests/terminal.py), typing Ctrl-C once interrupt_when shows."""
        return terminal.run(
            [sys.executable, RALPH, *args],
            cwd=self.work,
            env=self.env(TERM="xterm-256color", **env),
            columns=columns,
            interrupt_when=interrupt_when,
        )


class ScenarioTestCase(unittest.TestCase):
    def scenario(self):
        root = tempfile.mkdtemp(prefix="ralph-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        # macOS puts temporary files behind a symlink; git reports real paths.
        return Scenario(os.path.realpath(root))
