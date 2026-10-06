"""Checkout: the only module that talks to git."""

import os
from dataclasses import dataclass
from typing import Optional

from ralph import proc
from ralph.errors import RalphError

# Variables that would point git at an enclosing repository instead of the one asked about.
_REPOSITORY_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR")


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    message: str

    @property
    def short(self) -> str:
        return self.sha[:9]


def problems() -> list[str]:
    """What stops git from being used, if anything."""
    if not proc.on_path("git"):
        return ["git is not on PATH; install git"]
    return []


def remote_tags(repository: str) -> list[str]:
    """The tag names in repository, listed anonymously: no credentials and no prompts."""
    env = {name: value for name, value in os.environ.items() if name not in _REPOSITORY_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    listing = proc.completed(["git", "-c", "credential.helper=", "ls-remote", "--tags", "--refs", repository], env=env)
    if listing.returncode != 0:
        detail = "\n".join(("  " + line).rstrip() for line in listing.stderr.strip().splitlines())
        raise RalphError(f"could not list the versions in {repository}:\n{detail}")
    prefix = "refs/tags/"
    refs = (line.split("\t", 1)[-1] for line in listing.stdout.splitlines())
    return [ref[len(prefix) :] for ref in refs if ref.startswith(prefix)]


class Checkout:
    def __init__(self, root: str):
        self.root = root

    @classmethod
    def at(cls, directory: str) -> "Checkout":
        """The checkout containing directory."""
        if not proc.succeeds(["git", "rev-parse", "--show-toplevel"], cwd=directory):
            raise RalphError(f"{directory} is not inside a git repository")
        return cls(proc.output(["git", "rev-parse", "--show-toplevel"], cwd=directory).strip())

    def _git(self, *args: str) -> str:
        return proc.output(("git",) + args, cwd=self.root)

    def is_clean(self) -> bool:
        return self._git("status", "--porcelain") == ""

    def current_branch(self) -> Optional[str]:
        """The checked-out branch, or None when HEAD is detached."""
        return self._git("branch", "--show-current").strip() or None

    def switch(self, branch: str) -> None:
        """Checks branch out, creating it at HEAD if it does not exist."""
        if proc.succeeds(["git", "rev-parse", "--verify", "--quiet", "refs/heads/" + branch], cwd=self.root):
            self._git("switch", "--quiet", branch)
        else:
            self._git("switch", "--quiet", "--create", branch)

    def tags_at_head(self) -> list[str]:
        """The names of the tags pointing at HEAD."""
        return self._git("tag", "--points-at", "HEAD").split()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def resolve(self, revision: str) -> Optional[str]:
        """The full sha of the commit revision names, or None when it names none."""
        found = proc.completed(["git", "rev-parse", "--verify", "--quiet", revision + "^{commit}"], cwd=self.root)
        return found.stdout.strip() if found.returncode == 0 else None

    def merge_base(self, a: str, b: str) -> str:
        if not proc.succeeds(["git", "rev-parse", "--verify", "--quiet", b], cwd=self.root):
            raise RalphError(f"there is no branch {b} to take the run base from")
        return self._git("merge-base", a, b).strip()

    def push(self, branch: str, remote: str = "origin") -> None:
        """Pushes branch to the branch of the same name on remote, and has the local branch track it."""
        if self.resolve("refs/heads/" + branch) is None:
            raise RalphError(f"there is no branch {branch} in this repository to push")
        if not proc.succeeds(["git", "remote", "get-url", remote], cwd=self.root):
            raise RalphError(f"this repository has no remote named {remote} to push {branch} to")
        pushed = proc.completed(["git", "push", "--set-upstream", remote, f"refs/heads/{branch}"], cwd=self.root)
        if pushed.returncode != 0:
            detail = "\n".join(("  " + line).rstrip() for line in pushed.stderr.strip().splitlines())
            raise RalphError(f"could not push {branch} to {remote}:\n{detail}")

    def commits(self, since: str, until: str = "HEAD", limit: Optional[int] = None) -> list[Commit]:
        """The commits in since..until, newest first."""
        args = ["log", "--format=%H%x00%ad%x00%B%x01", "--date=short"]
        if limit is not None:
            args.append(f"-n{limit}")
        records = self._git(*args, f"{since}..{until}").split("\x01")
        commits = []
        for record in records:
            record = record.strip("\n")
            if record:
                sha, date, message = record.split("\x00", 2)
                commits.append(Commit(sha, date, message.strip()))
        return commits
