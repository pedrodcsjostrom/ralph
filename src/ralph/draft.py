"""Draft: the pull request draft, assembled from the records the loop keeps of a spec's runs.

It describes the whole spec's work on its integration branch: the tickets and
review rounds of every run of the spec on that branch, and how the latest run
ended. No agent writes any of it, so every line traces back to the tracker or
the git history. Every run leaves one in its run directory, however it ended;
the publish command opens the pull request from the latest.
"""

import os
from collections.abc import Iterable, Sequence
from dataclasses import replace

from ralph.checkout import Commit
from ralph.record import ReviewRoundRecord, RunOutcome, RunRecord, TicketOutcome, TicketRecord

FILE = "pull-request.md"


def _short(sha: str) -> str:
    return f"`{sha[:9]}`"


def _times(n: int, what: str) -> str:
    return f"{n} {what}" if n == 1 else f"{n} {what}s"


def _numbers(numbers: Iterable[int]) -> str:
    return ", ".join(f"#{n}" for n in numbers)


def _whole(records: Sequence[RunRecord]) -> tuple[list[TicketRecord], list[ReviewRoundRecord]]:
    """The tickets and review rounds of runs, oldest run first, as one spec's work.

    A ticket attempted in several runs is one ticket: its attempts and commits add up, and its
    outcome is the latest. Review rounds are numbered on from the earlier runs' rounds.
    """
    tickets: dict[int, TicketRecord] = {}
    rounds: list[ReviewRoundRecord] = []
    for record in records:
        before = len(rounds)
        rounds += [replace(r, round=before + r.round) for r in record.review_rounds]
        for t in record.tickets:
            seen = tickets.get(t.number)
            if seen is None:
                origin = before + t.from_review_round if t.from_review_round else None
                tickets[t.number] = replace(t, from_review_round=origin, commits=list(t.commits))
            else:
                seen.attempts += t.attempts
                seen.commits += t.commits
                seen.outcome = t.outcome
    return list(tickets.values()), rounds


class _Draft:
    def __init__(self, records: Sequence[RunRecord], commits: Iterable[Commit]):
        # The latest run says how the work ended, and what of it is unreviewed.
        self.record = records[-1]
        self.tickets, self.review_rounds = _whole(records)
        commits = list(reversed(list(commits)))
        self.subjects = {c.sha: (c.message.splitlines() or [""])[0] for c in commits}
        accounted = {sha for t in self.tickets if t.outcome == TicketOutcome.CLOSED for sha in t.commits}
        # Commits on the branch since the run base that no closed ticket of any run accounts for: work
        # from an attempt that did not finish its ticket, or from outside ralph.
        self.unaccounted = [c.sha for c in commits if c.sha not in accounted]

    def commit(self, sha: str) -> str:
        subject = self.subjects.get(sha)
        return f"{_short(sha)} {subject}" if subject else _short(sha)

    def render(self) -> str:
        r = self.record
        sections = [
            f"Implements spec #{r.spec} on `{r.branch}`, from base {_short(r.base)}.",
            "## How the run ended\n\n" + self.ending(),
            "## Tickets\n\n" + ("\n".join(self.ticket(t) for t in self.tickets) or "None."),
            "## Review rounds\n\n" + ("\n".join(self.rounds()) or "None."),
        ]
        given_up = [t for t in self.tickets if t.outcome == TicketOutcome.GIVEN_UP]
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
        if self.record.outcome == RunOutcome.ERROR:
            return f"Stopped by an unexpected error in ralph:\n\n{fence}text\n{self.record.reason}\n{fence}"
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
        for r in self.review_rounds:
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


def write(run_dir: str, records: Sequence[RunRecord], commits: Iterable[Commit]) -> str:
    """Writes the draft into run_dir and returns its path.

    records are those of the spec's runs on the integration branch, oldest first, ending with the
    run in run_dir. commits are the commits on the integration branch since the run base.
    """
    path = os.path.join(run_dir, FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(_Draft(records, commits).render())
    os.replace(path + ".tmp", path)
    return path
