"""Tracker: the only module that talks to GitHub, through the GitHub CLI."""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ralph import proc
from ralph.errors import RalphError


@dataclass(frozen=True)
class Ticket:
    """A sub-issue of a spec, as the frontier needs to see it."""

    number: int
    title: str
    is_open: bool
    labels: Tuple[str, ...]
    open_blockers: int


@dataclass(frozen=True)
class TicketDetails:
    """What an agent is told about its ticket."""

    number: int
    title: str
    url: str
    body: str
    comments: Tuple[str, ...]

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


def problems() -> List[str]:
    """What stops the GitHub CLI from being used, if anything."""
    if not proc.on_path("gh"):
        return ["the GitHub CLI (gh) is not on PATH; install it from https://cli.github.com"]
    if not proc.succeeds(["gh", "auth", "status"]):
        return ["the GitHub CLI (gh) is not logged in; run `gh auth login`"]
    return []


def _json_documents(text: str) -> List[Any]:
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
    def __init__(self, directory: str):
        self.directory = directory
        self.repo = self._json("repo", "view", "--json", "nameWithOwner")["nameWithOwner"]

    def _gh(self, *args: str) -> str:
        return proc.output(("gh",) + args, cwd=self.directory)

    def _json(self, *args: str) -> Dict[str, Any]:
        return json.loads(self._gh(*args))

    def spec_title(self, spec: int) -> str:
        return self._json("issue", "view", str(spec), "--repo", self.repo, "--json", "title")["title"]

    def tickets(self, spec: int) -> List[Ticket]:
        out = self._gh("api", "--paginate", "repos/%s/issues/%d/sub_issues?per_page=100" % (self.repo, spec))
        try:
            pages = _json_documents(out)
        except ValueError as e:
            raise RalphError("could not read the tickets of #%d: %s" % (spec, e))
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
        issue = self._json("issue", "view", str(number), "--repo", self.repo, "--json", "number,title,url,body,comments")
        return TicketDetails(
            number=issue["number"],
            title=issue["title"],
            url=issue["url"],
            body=issue.get("body") or "",
            comments=tuple(c["body"] for c in issue.get("comments", [])),
        )

    def close(self, number: int, comment: str) -> None:
        self._gh("issue", "close", str(number), "--repo", self.repo, "--comment", comment)
