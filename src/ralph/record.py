"""Record: what a run did, ticket by ticket and review round by review round.

The loop keeps it as `run.json` in the run directory, rewritten after every
change, so it is there for the pull request draft and for a runner
investigating a surprising result, however the run ended.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

FILE = "run.json"


class TicketOutcome:
    """Where a ticket stands in a run."""

    OPEN = "open"
    CLOSED = "closed"
    # It spent its attempts without closing.
    GIVEN_UP = "given up"


class RunOutcome:
    """How a run ended."""

    COMPLETE = "complete"
    STOPPED = "stopped"


@dataclass
class TicketRecord:
    number: int
    title: str
    # The review round whose finding the ticket was created from, None for a ticket of the original split.
    from_review_round: Optional[int] = None
    attempts: int = 0
    outcome: str = TicketOutcome.OPEN
    # The commits that implemented it, full shas, oldest first.
    commits: list[str] = field(default_factory=list)


@dataclass
class ReviewRoundRecord:
    round: int
    fixed_point: str
    # The head the review looked at; the next round's fixed point.
    head: str
    findings_file: str
    # The fix tickets of the previous round that the diff since fixed_point was meant to resolve.
    resolves: list[int] = field(default_factory=list)
    # The fix tickets created from this round's findings; none means the round was clean.
    fix_tickets: list[int] = field(default_factory=list)
    # Whether the round got as far as publishing all its findings; a round that broke off never passes for clean.
    finished: bool = False


@dataclass
class RunRecord:
    spec: int
    branch: str
    base: str
    tickets: list[TicketRecord] = field(default_factory=list)
    review_rounds: list[ReviewRoundRecord] = field(default_factory=list)
    # None while the run is going, then a RunOutcome.
    outcome: Optional[str] = None
    # Why the run stopped, when it did not complete.
    reason: Optional[str] = None
    # Commits on the integration branch that no review round covered, full shas, oldest first.
    unreviewed: list[str] = field(default_factory=list)

    @property
    def ended_cleanly(self) -> bool:
        """Whether the run completed: every ticket closed and the last review round clean."""
        return self.outcome == RunOutcome.COMPLETE

    def ticket(self, number: int, title: str, from_review_round: Optional[int] = None) -> TicketRecord:
        """The record of a ticket, started on first use."""
        for t in self.tickets:
            if t.number == number:
                return t
        record = TicketRecord(number, title, from_review_round)
        self.tickets.append(record)
        return record

    @classmethod
    def load(cls, run_dir: str) -> "RunRecord":
        """The record a run kept in run_dir. Raises OSError or ValueError when it is missing or unreadable."""
        with open(os.path.join(run_dir, FILE), encoding="utf-8") as f:
            fields = json.load(f)
        try:
            tickets = [TicketRecord(**t) for t in fields.pop("tickets")]
            rounds = [ReviewRoundRecord(**r) for r in fields.pop("review_rounds")]
            return cls(**fields, tickets=tickets, review_rounds=rounds)
        except (KeyError, TypeError) as e:
            raise ValueError(f"{FILE} is not a run record: {e}") from e

    def save(self, run_dir: str) -> None:
        path = os.path.join(run_dir, FILE)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
            f.write("\n")
        os.replace(path + ".tmp", path)
