"""Loop: the deterministic core of a run.

It decides which ticket is next, whether it is done and when to stop. It
knows Tracker, Agent and Checkout only by what they answer and perform, never
by how. A run keeps no state of its own between invocations: everything it
needs is read from the tracker and the integration branch.
"""

import os
import re
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

from ralph import draft, findings, project, prompts, runs, verify
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.config import Config
from ralph.console import Console
from ralph.errors import AlreadyReported, RalphError
from ralph.record import ReviewRoundRecord, RunOutcome, RunRecord, TicketOutcome
from ralph.tracker import READY, Ticket, Tracker

# Where a run that stopped on an unexpected error keeps its traceback, in the run directory.
ERROR_FILE = "error.txt"

# How an agent ends its final message on a ticket.
PROMISE_COMPLETE = "<promise>TICKET COMPLETE</promise>"
PROMISE_BLOCKED = "<promise>TICKET BLOCKED</promise>"


def frontier(tickets: Iterable[Ticket], leave_alone: Iterable[int] = ()) -> list[Ticket]:
    """The tickets that are open, ready for an agent and not blocked, lowest number first."""
    skip = set(leave_alone)
    return sorted(
        (t for t in tickets if t.is_open and READY in t.labels and t.open_blockers == 0 and t.number not in skip),
        key=lambda t: t.number,
    )


def integration_branch(spec: int, title: str) -> str:
    """The branch a spec lands on when a run starts from the main branch, e.g. spec/1-widget-sorting."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).lstrip("-")[:40].rstrip("-")
    return f"spec/{spec}-{slug}" if slug else f"spec/{spec}"


def _open_list(tickets: Iterable[Ticket]) -> str:
    """One "#N title" line per open ticket, lowest number first."""
    return "\n".join(f"#{t.number} {t.title}" for t in sorted(tickets, key=lambda t: t.number) if t.is_open)


@dataclass(frozen=True)
class _Start:
    """Where a run or a watched iteration starts, once the checkout is on the integration branch."""

    branch: str
    run_base: str
    context: prompts.RunContext


class Loop:
    def __init__(self, spec: int, tracker: Tracker, agent: Agent, checkout: Checkout, console: Console, config: Config):
        self.spec = spec
        self.config = config
        self.tracker = tracker
        self.agent = agent
        self.checkout = checkout
        self.console = console

    def run(self) -> None:
        """Implements and reviews until a review round is clean. Raises RalphError when the run cannot end cleanly."""
        _Run(self, self._start()).run()

    def watch(self) -> None:
        """Opens an interactive session on the ticket an unattended run would implement next, and closes nothing.

        It starts exactly as a run does, so the session sees the same branch, ticket and prompt,
        except that the prompt tells the agent a human is present.
        """
        start = self._start()
        ready = frontier(self.tracker.tickets(self.spec))
        if not ready:
            raise RalphError(f"no ticket of spec #{self.spec} is on the frontier")
        n = ready[0].number
        self.console.say(f"ticket #{n} of spec #{self.spec} on {start.branch}")
        prompt = prompts.implement(
            start.context,
            self.tracker.ticket_details(n),
            fixed_point=self.checkout.head(),
            commits=self.checkout.commits(start.run_base, limit=prompts.RECENT_COMMITS),
            watched=True,
        )
        status = self.agent.interactive(prompt)
        if status != 0:
            raise RalphError(f"the session on #{n} ended with exit status {status}; #{n} stays open")
        self.console.say(
            f"#{n} stays open. When the work is good, close it: gh issue close {n} --repo {self.tracker.repo}"
        )

    def _start(self) -> _Start:
        if not self.checkout.is_clean():
            raise RalphError("the working tree is not clean; commit or discard your changes first")
        branch = self.checkout.current_branch()
        if branch is None:
            raise RalphError("HEAD is detached; check out a branch first")

        title = self.tracker.spec_title(self.spec)
        if not self.tracker.tickets(self.spec):
            raise RalphError(
                f"spec #{self.spec} has no tickets. Split it into tickets first with `ralph split {self.spec}`, "
                f"or by hand: sub-issues of #{self.spec} labelled {READY}, with their blockers recorded as issue "
                "dependencies."
            )

        # The whole spec lands on one integration branch and main never gets a
        # commit. Started from any other branch, that branch is the integration branch.
        main = self.config.main_branch
        configured_base = self._configured_run_base()
        if branch == main:
            branch = integration_branch(self.spec, title)
            self.checkout.switch(branch)
        # Taken on the integration branch: a rerun from main after main moved on keeps the branch's own run base.
        run_base = configured_base or self.checkout.merge_base("HEAD", main)
        context = prompts.RunContext(
            spec=self.spec,
            repo=self.tracker.repo,
            branch=branch,
            rules={kind: project.rules(self.checkout.root, kind) for kind in project.RULES},
        )
        return _Start(branch, run_base, context)

    def _configured_run_base(self) -> Optional[str]:
        """The configured run base, resolved to a full sha, or None when the run base is the merge base."""
        if self.config.run_base is None:
            return None
        base = self.checkout.resolve(self.config.run_base)
        if base is None:
            raise RalphError(f"the run base {self.config.run_base!r} (run_base) is not a commit in this repository")
        return base


class _Run:
    """One run of the loop, from the moment it is on the integration branch until it stops.

    It keeps its record and logs in a fresh run directory.
    """

    def __init__(self, loop: Loop, start: _Start):
        self.spec = loop.spec
        self.config = loop.config
        self.tracker = loop.tracker
        self.agent = loop.agent
        self.checkout = loop.checkout
        self.console = loop.console
        self.branch = start.branch
        self.base = start.run_base
        self.context = start.context
        # The commit the next review round compares the work against.
        self.fixed_point = start.run_base
        self.iteration = 0
        self.attempts: dict[int, int] = {}
        # Tickets that spent their attempts without closing. They stay open on
        # the tracker, so a rerun tries them again.
        self.left_alone: set[int] = set()
        self.run_dir = runs.create(self.checkout.root)
        self.record = RunRecord(spec=self.spec, branch=self.branch, base=self.base)
        self.record.save(self.run_dir)

    def run(self) -> None:
        self.console.say(f"spec #{self.spec} on {self.branch}, base {self.base[:9]}, logs in {self.run_dir}")
        try:
            self._rounds()
        except RalphError as e:
            self.console.error(str(e))
            self._end(RunOutcome.STOPPED, str(e))
            raise AlreadyReported(1) from None
        except KeyboardInterrupt:
            self.console.error("interrupted")
            self._end(RunOutcome.STOPPED, "interrupted")
            raise AlreadyReported(130) from None
        except Exception as e:
            # A bug in ralph or a surprise from a tool it drives: the run still leaves its record and draft.
            reason = f"{type(e).__name__}: {e}"
            path = os.path.join(self.run_dir, ERROR_FILE)
            with open(path, "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            self.console.error(f"unexpected error, a bug in ralph: {reason}; its traceback is in {path}")
            self._end(RunOutcome.ERROR, reason)
            raise AlreadyReported(1) from e
        self.console.say(
            f"complete after {self.iteration} iterations. "
            f"Spec #{self.spec} is implemented and reviewed on {self.branch} (base {self.base[:9]})."
        )
        self.console.say("nothing was pushed. Look it over, then open the pull request.")
        self._end(RunOutcome.COMPLETE)

    def _end(self, outcome: str, reason: Optional[str] = None) -> None:
        """Records how the run ended and leaves the pull request draft, then points the runner at it."""
        self.record.outcome, self.record.reason = outcome, reason
        if outcome != RunOutcome.COMPLETE:
            self.record.unreviewed = [c.sha for c in reversed(self.checkout.commits(self.fixed_point))]
        self.record.save(self.run_dir)
        path = draft.write(self.run_dir, self._history(), self.checkout.commits(self.base))
        self.console.say(f"the pull request draft is {path}")

    def _history(self) -> list[RunRecord]:
        """The records of the earlier runs of this spec on this integration branch, oldest first, then this run's.

        A run directory without a readable record is skipped: the draft is never held up by an old run.
        """
        earlier = []
        for run_dir in runs.every(self.checkout.root):
            if run_dir == self.run_dir:
                continue
            try:
                record = RunRecord.load(run_dir)
            except (OSError, ValueError):
                continue
            if record.spec == self.spec and record.branch == self.branch:
                earlier.append(record)
        return earlier + [self.record]

    def _rounds(self) -> None:
        """Implements the frontier, then reviews, until a review round finds nothing or nothing is left to review.

        The first round reviews everything since the run base. Each later round reviews only what
        was committed since the previous one, the fixes it asked for, so the loop narrows instead
        of reviewing everything forever.
        """
        fix_tickets: list[int] = []
        round_ = 0
        while True:
            self._implement_frontier()
            head = self.checkout.head()
            if head == self.fixed_point:
                self.console.say(f"nothing to review since {self.fixed_point[:9]}")
                return
            if round_ >= self.config.max_review_rounds:
                raise RalphError(
                    f"the review round budget ({self.config.max_review_rounds}) is spent; "
                    f"these commits since {self.fixed_point[:9]} are unreviewed:\n{self._unreviewed()}"
                )
            if self.iteration >= self.config.max_iterations:
                raise RalphError(
                    f"the iteration budget ({self.config.max_iterations}) is spent before review round "
                    f"{round_ + 1}; rerun to carry on. These commits since {self.fixed_point[:9]} are unreviewed:\n"
                    f"{self._unreviewed()}"
                )
            round_ += 1
            fix_tickets = self._review(round_, fix_tickets)
            if not fix_tickets:
                return
            self.fixed_point = head

    def _implement_frontier(self) -> None:
        """Implements the frontier until it is empty, and stops the run if that leaves tickets open."""
        while True:
            tickets = self.tracker.tickets(self.spec)
            ready = frontier(tickets, self.left_alone)
            if not ready:
                break
            if self.iteration >= self.config.max_iterations:
                raise RalphError(
                    f"the iteration budget ({self.config.max_iterations}) is spent with work left; "
                    f"rerun to carry on. Still open:\n{_open_list(tickets)}"
                )
            self._implement(ready[0])

        still_open = _open_list(self.tracker.tickets(self.spec))
        if still_open:
            raise RalphError(
                f"stopping, these tickets are open and nothing on the frontier can be implemented:\n{still_open}"
            )

    def _unreviewed(self) -> str:
        """One "<short sha> <subject>" line per commit since the fixed point, oldest first."""
        return "\n".join(
            f"{c.short} {c.message.splitlines()[0] if c.message else ''}"
            for c in reversed(self.checkout.commits(self.fixed_point))
        )

    def _next_iteration(self, what: str, heading_detail: str = "") -> str:
        """Counts a new iteration doing what, such as "ticket #3, attempt 1/2", and heads its output.

        Returns the label of its working indicator.
        """
        self.iteration += 1
        count = f"{self.iteration}/{self.config.max_iterations}"
        self.console.heading(f"[{count}] {what}{heading_detail}")
        return f"iteration {count}, {what}"

    def _implement(self, ticket: Ticket) -> None:
        n = ticket.number
        attempt = self.attempts[n] = self.attempts.get(n, 0) + 1
        label = self._next_iteration(f"ticket #{n}, attempt {attempt}/{self.config.max_attempts}")

        before = self.checkout.head()
        prompt = prompts.implement(
            self.context,
            self.tracker.ticket_details(n),
            fixed_point=before,
            commits=self.checkout.commits(self.base, limit=prompts.RECENT_COMMITS),
        )
        log = os.path.join(self.run_dir, f"{self.iteration:02d}-ticket-{n}.jsonl")
        record = self.record.ticket(n, ticket.title)
        record.attempts = attempt
        self.record.save(self.run_dir)
        with self.console.waiting(label) as wait:
            final = self.agent.run(prompt, log, self.console.prose, wait.doing, self.console.passthrough)
            self._check_checkout(f"iteration {self.iteration} (ticket #{n})")
            reason = self._not_done(n, attempt, final, before) or self._verify(n)
        if reason is None:
            commits = list(reversed(self.checkout.commits(before)))
            self.tracker.close(n, f"Implemented by ralph on `{self.branch}`: {' '.join(c.short for c in commits)}")
            record.outcome = TicketOutcome.CLOSED
            record.commits = [c.sha for c in commits]
            self.record.save(self.run_dir)
            self.console.say(f"closed #{n}")
            return
        self.console.say(f"#{n} stays open, {reason}")
        if attempt >= self.config.max_attempts:
            self.left_alone.add(n)
            record.outcome = TicketOutcome.GIVEN_UP
            self.record.save(self.run_dir)
            self.console.say(f"giving up on #{n} after {attempt} attempts; it is left alone for the rest of this run")

    def _review(self, round_: int, resolves: list[int]) -> list[int]:
        """Runs one review round and publishes its findings as fix tickets. Returns their numbers."""
        label = self._next_iteration(
            f"review round {round_}/{self.config.max_review_rounds}", f", since {self.fixed_point[:9]}"
        )

        head = self.checkout.head()
        findings_file = os.path.join(self.run_dir, f"review-{round_}.json")
        record = ReviewRoundRecord(round_, self.fixed_point, head, findings_file, resolves=list(resolves))
        self.record.review_rounds.append(record)
        self.record.save(self.run_dir)
        prompt = prompts.review(self.context, self.fixed_point, round_, findings_file, resolves)
        log = os.path.join(self.run_dir, f"{self.iteration:02d}-review-{round_}.jsonl")
        with self.console.waiting(label) as wait:
            self.agent.run(prompt, log, self.console.prose, wait.doing, self.console.passthrough)
        culprit = f"iteration {self.iteration} (review round {round_})"
        self._check_checkout(culprit)
        if self.checkout.head() != head:
            raise RalphError(f"{culprit} made commits, but a review changes nothing; inspect them, then rerun")

        try:
            found = findings.read(findings_file)
        except findings.Unreadable as e:
            # A broken review must never pass for a clean one.
            raise RalphError(f"review round {round_} {e}; rerun to review again") from None
        if not found:
            self.console.say(f"review round {round_} found nothing")
        for finding in found:
            n = self.tracker.create_ticket(self.spec, finding.title, finding.ticket_body(self.spec), [READY])
            record.fix_tickets.append(n)
            self.record.ticket(n, finding.title, from_review_round=round_)
            self.record.save(self.run_dir)
            self.console.say(f"review finding is now #{n}: {finding.title}")
        record.finished = True
        self.record.save(self.run_dir)
        return record.fix_tickets

    def _check_checkout(self, culprit: str) -> None:
        """Stops the run unless the checkout is clean and on the integration branch, so nothing builds on a mess."""
        if not self.checkout.is_clean():
            raise RalphError(f"{culprit} left uncommitted changes; inspect them, then rerun")
        branch = self.checkout.current_branch()
        if branch != self.branch:
            where = "HEAD detached" if branch is None else f"the checkout on {branch}"
            raise RalphError(f"{culprit} left {where}, off {self.branch}; switch back, then rerun")

    def _not_done(self, number: int, attempt: int, final: str, before: str) -> Optional[str]:
        """Why the attempt that started at before did not finish its ticket, or None if it did.

        An agent that reports the ticket blocked says why in its final message; that goes on the
        ticket, where the next attempt reads it, since agents never touch issues themselves.
        """
        if PROMISE_COMPLETE not in final:
            if PROMISE_BLOCKED not in final:
                return "the agent did not report it complete"
            said = final[: final.index(PROMISE_BLOCKED)].strip()
            quoted = "\n".join(f"> {line}".rstrip() for line in said.splitlines()) or "> (no reason given)"
            self.tracker.comment(number, f"ralph: attempt {attempt} ended blocked. The agent said:\n\n{quoted}")
            return "the agent reported it blocked"
        if self.checkout.head() == before:
            return "the agent reported it complete but made no commit"
        return None

    def _verify(self, number: int) -> Optional[str]:
        """Runs the verify command, if any. Why it failed, or None if it passed or there is none."""
        if self.config.verify is None:
            return None
        with self.console.waiting(f"verify: {self.config.verify}"):
            failure = verify.run(self.config.verify, self.checkout.root)
        if failure is None:
            return None
        # The next attempt reads the ticket's comments, so it learns what went wrong.
        fence = "```"
        self.tracker.comment(
            number,
            f"ralph: `{failure.command}` failed after this attempt.\n\n{fence}\n{failure.tail()}\n{fence}",
        )
        return f"`{failure.command}` failed with exit status {failure.status}"
