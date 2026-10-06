"""Findings: what a review round wrote, read strictly so a broken review is never mistaken for a clean one.

A findings file is a JSON array with one object per fix ticket the review wants:

    [{"title": "...", "what_to_build": "...", "acceptance_criteria": ["...", "..."]}]

An empty array means the review found nothing.
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    title: str
    what_to_build: str
    acceptance_criteria: tuple[str, ...]

    def ticket_body(self, spec: int) -> str:
        """The body of the fix ticket, in the structure a split of the spec produces."""
        criteria = "\n".join(f"- [ ] {c}" for c in self.acceptance_criteria)
        return (
            f"## Parent\n\n#{spec}\n\n"
            f"## What to build\n\n{self.what_to_build.strip()}\n\n"
            f"## Acceptance criteria\n\n{criteria}\n\n"
            "## Blocked by\n\nNone (can start immediately)\n"
        )


class Unreadable(Exception):
    """The findings file is missing or malformed. The message reads on from "review round <n> "."""


class Malformed(Exception):
    pass


def read(path: str) -> list[Finding]:
    """The findings in the file at path. Raises Unreadable if it is missing or malformed."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        raise Unreadable(f"wrote no findings to {path}") from None
    try:
        return _parse(json.loads(text))
    except ValueError as e:
        raise Unreadable(f"wrote findings to {path} that are not valid JSON ({e})") from None
    except Malformed as e:
        raise Unreadable(f"wrote malformed findings to {path}: {e}") from None


def _parse(document: object) -> list[Finding]:
    if not isinstance(document, list):
        raise Malformed("expected a JSON array of findings")
    return [_finding(i + 1, item) for i, item in enumerate(document)]


def _finding(position: int, item: object) -> Finding:
    if not isinstance(item, dict):
        raise Malformed(f"finding {position} is not an object")
    for key in ("title", "what_to_build"):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Malformed(f"finding {position} needs a non-empty string {key}")
    criteria = item.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or not all(isinstance(c, str) and c.strip() for c in criteria):
        raise Malformed(f"finding {position} needs acceptance_criteria, a non-empty list of non-empty strings")
    return Finding(item["title"].strip(), item["what_to_build"], tuple(c.strip() for c in criteria))
