"""Prompts: composes each iteration's prompt from ralph's generic instructions and the run context."""

import os
from dataclasses import dataclass
from typing import Sequence

from ralph.checkout import Commit
from ralph.tracker import TicketDetails

INSTRUCTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instructions")
FENCE = "```"

# How many of the integration branch's commits an agent is shown.
RECENT_COMMITS = 10


def _instructions(name: str) -> str:
    with open(os.path.join(INSTRUCTIONS, name + ".md"), encoding="utf-8") as f:
        return f.read().strip()


@dataclass(frozen=True)
class RunContext:
    spec: int
    repo: str
    branch: str


def implement(run: RunContext, ticket: TicketDetails, fixed_point: str, commits: Sequence[Commit]) -> str:
    """The prompt for one attempt at a ticket. commits are the integration branch's, newest first."""
    log = "\n".join("%s %s\n%s\n---" % (c.short, c.date, c.message) for c in commits)
    return "\n".join(
        [
            _instructions("implement"),
            "",
            "## Run context",
            "",
            "- Spec: #%d in %s" % (run.spec, run.repo),
            "- Integration branch: %s" % run.branch,
            "- Ticket: #%d" % ticket.number,
            "- Fixed point, the commit to review your work against: %s" % fixed_point,
            "",
            "### The ticket",
            "",
            FENCE + "json",
            ticket.as_json(),
            FENCE,
            "",
            "### Commits already on the integration branch, newest first",
            "",
            FENCE,
            log or "(none yet)",
            FENCE,
            "",
        ]
    )
