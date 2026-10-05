"""Checkout: the only module that talks to git."""

from dataclasses import dataclass
from typing import Optional

from ralph import proc
from ralph.errors import RalphError


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

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def merge_base(self, a: str, b: str) -> str:
        if not proc.succeeds(["git", "rev-parse", "--verify", "--quiet", b], cwd=self.root):
            raise RalphError(f"there is no branch {b} to take the run base from")
        return self._git("merge-base", a, b).strip()

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
