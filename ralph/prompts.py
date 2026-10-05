"""Prompts: composes each iteration's prompt from ralph's generic instructions and the run context."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

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
    # The project rules for each kind of iteration ("implement", "review"); empty or absent when there are none.
    rules: Mapping[str, str] = field(default_factory=dict)


def _with_rules(run: RunContext, kind: str) -> list[str]:
    """Ralph's generic instructions for kind, followed by the project's rules for it, if any.

    Project rules only ever add to the generic instructions; the run context always comes after both.
    """
    lines = [_instructions(kind), ""]
    rules = run.rules.get(kind, "").strip()
    if rules:
        lines += ["## Project rules", "", rules, ""]
    return lines


def implement(run: RunContext, ticket: TicketDetails, fixed_point: str, commits: Sequence[Commit]) -> str:
    """The prompt for one attempt at a ticket. commits are the integration branch's, newest first."""
    log = "\n".join(f"{c.short} {c.date}\n{c.message}\n---" for c in commits)
    return "\n".join(
        _with_rules(run, "implement")
        + [
            "## Run context",
            "",
            f"- Spec: #{run.spec} in {run.repo}",
            f"- Integration branch: {run.branch}",
            f"- Ticket: #{ticket.number}",
            f"- Fixed point, the commit to review your work against: {fixed_point}",
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


def review(run: RunContext, fixed_point: str, round_: int, findings_file: str, fix_tickets: Sequence[int]) -> str:
    """The prompt for one review round. fix_tickets are those the diff since fixed_point was meant to resolve."""
    lines = _with_rules(run, "review") + [
        "## Run context",
        "",
        f"- Spec: #{run.spec} in {run.repo}",
        f"- Integration branch: {run.branch}",
        f"- Fixed point, the commit to review the work against: {fixed_point}",
        f"- Review round: {round_}",
        f"- Findings file: {findings_file}",
    ]
    if fix_tickets:
        names = ", ".join(f"#{n}" for n in fix_tickets)
        lines.append(f"- This diff holds only the fixes for the previous review round's fix tickets: {names}")
    return "\n".join(lines + [""])
