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


def _with_rules(run: RunContext, kind: str, invocation: str) -> list[str]:
    """The bundled skill invocation, ralph's generic instructions for kind and the project's rules for it, if any.

    The prompt starts with the invocation, so Claude Code runs the bundled skill with the rest of the
    prompt as its arguments. Project rules only ever add to the generic instructions; the run context
    always comes after both.
    """
    lines = [invocation, "", _instructions(kind), ""]
    rules = run.rules.get(kind, "").strip()
    if rules:
        lines += ["## Project rules", "", rules, ""]
    return lines


# The run context line that tells a watched iteration's agent it is not alone.
WATCHED = "- A human is watching this iteration and will close the ticket: you may ask them questions."


def implement(
    run: RunContext, ticket: TicketDetails, fixed_point: str, commits: Sequence[Commit], watched: bool = False
) -> str:
    """The prompt for one attempt at a ticket. commits are the integration branch's, newest first.

    A watched attempt is an interactive session with a human present.
    """
    log = "\n".join(f"{c.short} {c.date}\n{c.message}\n---" for c in commits)
    return "\n".join(
        _with_rules(run, "implement", f"/ralph:implement #{ticket.number}")
        + [
            "## Run context",
            "",
            f"- Spec: #{run.spec} in {run.repo}",
            f"- Integration branch: {run.branch}",
            f"- Ticket: #{ticket.number}",
            f"- Fixed point, the commit to review your work against: {fixed_point}",
        ]
        + ([WATCHED] if watched else [])
        + [
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
    lines = _with_rules(run, "review", f"/ralph:code-review {fixed_point}") + [
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


def split(spec: int, title: str, repo: str) -> str:
    """The first prompt of an interactive session splitting spec into tickets."""
    return "\n".join(
        [f"/ralph:to-tickets #{spec}", "", _instructions("split"), "", "## Run context", ""]
        + [f"- Spec: #{spec} in {repo}", f"- Spec title: {title}", ""]
    )
