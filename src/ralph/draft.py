"""Draft: the pull request draft, assembled from the record the loop keeps of a run.

No agent writes any of it, so every line traces back to the tracker or the git
history. Every run leaves one in its run directory, however it ended; the
publish command opens the pull request from the latest.
"""

import os
from collections.abc import Iterable

from ralph.checkout import Commit
from ralph.record import RunRecord, TicketOutcome, TicketRecord

FILE = "pull-request.md"


def _short(sha: str) -> str:
    return f"`{sha[:9]}`"


def _times(n: int, what: str) -> str:
    return f"{n} {what}" if n == 1 else f"{n} {what}s"


def _numbers(numbers: Iterable[int]) -> str:
    return ", ".join(f"#{n}" for n in numbers)


class _Draft:
    def __init__(self, record: RunRecord, commits: Iterable[Commit]):
        self.record = record
        commits = list(reversed(list(commits)))
        self.subjects = {c.sha: (c.message.splitlines() or [""])[0] for c in commits}
        accounted = {sha for t in record.tickets if t.outcome == TicketOutcome.CLOSED for sha in t.commits}
        # Commits on the branch since the base that no ticket of this run closed with: work from an
        # attempt that did not finish its ticket, or from before this run.
        self.unaccounted = [c.sha for c in commits if c.sha not in accounted]

    def commit(self, sha: str) -> str:
        subject = self.subjects.get(sha)
        return f"{_short(sha)} {subject}" if subject else _short(sha)

    def render(self) -> str:
        r = self.record
        sections = [
            f"Implements spec #{r.spec} on `{r.branch}`, from base {_short(r.base)}.",
            "## How the run ended\n\n" + self.ending(),
            "## Tickets\n\n" + ("\n".join(self.ticket(t) for t in r.tickets) or "None."),
            "## Review rounds\n\n" + ("\n".join(self.rounds()) or "None."),
        ]
        given_up = [t for t in r.tickets if t.outcome == TicketOutcome.GIVEN_UP]
        if given_up:
            sections.append("## Given up on\n\n" + "\n".join(f"- #{t.number} {t.title}" for t in given_up))
        if r.unreviewed:
            sections.append("## Unreviewed commits\n\n" + self.commits(r.unreviewed))
        if self.unaccounted:
            sections.append("## Commits no closed ticket accounts for\n\n" + self.commits(self.unaccounted))
        return "\n\n".join(sections) + "\n"

    def ending(self) -> str:
        if self.record.ended_cleanly:
            return "Ended cleanly: every ticket is closed and nothing is left unreviewed."
        fence = "```"
        return f"Stopped before it could end cleanly:\n\n{fence}text\n{self.record.reason}\n{fence}"

    def ticket(self, t: TicketRecord) -> str:
        origin = f", a fix ticket from review round {t.from_review_round}" if t.from_review_round else ""
        if t.attempts:
            outcome = f"{t.outcome} after {_times(t.attempts, 'attempt')}"
        else:
            outcome = f"{t.outcome}, not attempted"
        return "\n".join([f"- #{t.number} {t.title}{origin}: {outcome}"] + [f"  - {self.commit(c)}" for c in t.commits])

    def rounds(self) -> list[str]:
        lines = []
        for r in self.record.review_rounds:
            resolves = f", the fixes for {_numbers(r.resolves)}" if r.resolves else ""
            if not r.finished:
                found = "did not finish" + (
                    f", after creating fix tickets {_numbers(r.fix_tickets)}" if r.fix_tickets else ""
                )
            elif r.fix_tickets:
                found = f"fix tickets {_numbers(r.fix_tickets)}"
            else:
                found = "found nothing"
            lines.append(f"- Round {r.round}, since {_short(r.fixed_point)}{resolves}: {found}")
        return lines

    def commits(self, shas: Iterable[str]) -> str:
        return "\n".join(f"- {self.commit(sha)}" for sha in shas)


def write(run_dir: str, record: RunRecord, commits: Iterable[Commit]) -> str:
    """Writes the draft for record into run_dir and returns its path.

    commits are the commits on the integration branch since the run base, for their subjects.
    """
    path = os.path.join(run_dir, FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(_Draft(record, commits).render())
    os.replace(path + ".tmp", path)
    return path
