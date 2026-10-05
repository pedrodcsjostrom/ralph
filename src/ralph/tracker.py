"""Tracker: the only module that talks to GitHub, through the GitHub CLI."""

import json
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Optional

from ralph import proc
from ralph.errors import RalphError
from ralph.progress import Progress


@dataclass(frozen=True)
class Ticket:
    """A sub-issue of a spec, as the frontier needs to see it."""

    number: int
    title: str
    is_open: bool
    labels: tuple[str, ...]
    open_blockers: int


@dataclass(frozen=True)
class TicketDetails:
    """What an agent is told about its ticket."""

    number: int
    title: str
    url: str
    body: str
    comments: tuple[str, ...]

    def as_json(self) -> str:
        return json.dumps(
            {
                "number": self.number,
                "title": self.title,
                "url": self.url,
                "body": self.body,
                "comments": list(self.comments),
            },
            indent=2,
        )


def problems() -> list[str]:
    """What stops the GitHub CLI from being used, if anything."""
    if not proc.on_path("gh"):
        return ["the GitHub CLI (gh) is not on PATH; install it from https://cli.github.com"]
    if not proc.succeeds(["gh", "auth", "status"]):
        return ["the GitHub CLI (gh) is not logged in; run `gh auth login`"]
    return []


def _json_documents(text: str) -> list[Any]:
    """Every JSON document in text. `gh api --paginate` prints one per page, back to back."""
    decoder = json.JSONDecoder()
    documents, i = [], 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i == len(text):
            return documents
        document, i = decoder.raw_decode(text, i)
        documents.append(document)


class Tracker:
    def __init__(self, directory: str, progress: Optional[Progress] = None):
        """progress, if given, shows every call to GitHub as a wait."""
        self.directory = directory
        self.progress = progress
        self.repo = self._json("finding the repository", "repo", "view", "--json", "nameWithOwner")["nameWithOwner"]

    def _gh(self, doing: str, *args: str, input: Optional[str] = None) -> str:
        """Runs gh with args; doing says what for, as in "GitHub: closing #3"."""
        with self.progress.waiting(f"GitHub: {doing}") if self.progress else nullcontext():
            return proc.output(("gh",) + args, cwd=self.directory, input=input)

    def _json(self, doing: str, *args: str) -> dict[str, Any]:
        return json.loads(self._gh(doing, *args))

    def spec_title(self, spec: int) -> str:
        return self._json(f"reading #{spec}", "issue", "view", str(spec), "--repo", self.repo, "--json", "title")[
            "title"
        ]

    def tickets(self, spec: int) -> list[Ticket]:
        out = self._gh(
            f"reading the tickets of #{spec}",
            "api",
            "--paginate",
            f"repos/{self.repo}/issues/{spec}/sub_issues?per_page=100",
        )
        try:
            pages = _json_documents(out)
        except ValueError as e:
            raise RalphError(f"could not read the tickets of #{spec}: {e}") from e
        return [
            Ticket(
                number=issue["number"],
                title=issue["title"],
                is_open=issue["state"] == "open",
                labels=tuple(label["name"] for label in issue.get("labels", [])),
                open_blockers=(issue.get("issue_dependencies_summary") or {}).get("blocked_by", 0),
            )
            for page in pages
            for issue in page
        ]

    def ticket_details(self, number: int) -> TicketDetails:
        issue = self._json(
            f"reading #{number}",
            "issue",
            "view",
            str(number),
            "--repo",
            self.repo,
            "--json",
            "number,title,url,body,comments",
        )
        return TicketDetails(
            number=issue["number"],
            title=issue["title"],
            url=issue["url"],
            body=issue.get("body") or "",
            comments=tuple(c["body"] for c in issue.get("comments", [])),
        )

    def close(self, number: int, comment: str) -> None:
        self._gh(f"closing #{number}", "issue", "close", str(number), "--repo", self.repo, "--comment", comment)

    def comment(self, number: int, body: str) -> None:
        self._gh(f"commenting on #{number}", "issue", "comment", str(number), "--repo", self.repo, "--body", body)

    def open_pull_request(self, base: str, head: str, title: str, body: str) -> str:
        """Opens a pull request of the pushed branch head into base and returns its URL."""
        out = self._gh(
            f"opening a pull request of {head}",
            "pr",
            "create",
            "--repo",
            self.repo,
            "--base",
            base,
            "--head",
            head,
            "--title",
            title,
            "--body-file",
            "-",
            input=body,
        )
        return out.strip().splitlines()[-1]

    def ensure_label(self, name: str, description: str, color: str) -> bool:
        """Creates the label on the repository unless it is there already, as it is; says whether it created it."""
        listed = json.loads(
            self._gh("reading the labels", "label", "list", "--repo", self.repo, "--json", "name", "--limit", "1000")
        )
        if name in (label["name"] for label in listed):
            return False
        self._gh(
            f"creating the {name} label",
            "label",
            "create",
            name,
            "--repo",
            self.repo,
            "--description",
            description,
            "--color",
            color,
        )
        return True

    def create_ticket(self, spec: int, title: str, body: str, labels: Sequence[str]) -> int:
        """Opens a new ticket as a sub-issue of spec and returns its number."""
        fields = json.dumps({"title": title, "body": body, "labels": list(labels)})
        created = json.loads(
            self._gh(
                "opening a fix ticket",
                "api",
                f"repos/{self.repo}/issues",
                "--method",
                "POST",
                "--input",
                "-",
                input=fields,
            )
        )
        # Sub-issues are linked by the issue's id, not its number.
        self._gh(
            f"adding #{created['number']} to #{spec}",
            "api",
            f"repos/{self.repo}/issues/{spec}/sub_issues",
            "--method",
            "POST",
            "-F",
            f"sub_issue_id={created['id']}",
        )
        return created["number"]
