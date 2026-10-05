"""Loop: the deterministic core of a run.

It decides which ticket is next, whether it is done and when to stop. It
knows Tracker, Agent and Checkout only by what they answer and perform, never
by how. A run keeps no state of its own between invocations: everything it
needs is read from the tracker and the integration branch.
"""

import os
import re
from collections.abc import Iterable
from typing import Optional

from ralph import prompts, runs, verify
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.config import Config
from ralph.console import Console
from ralph.errors import RalphError
from ralph.tracker import Ticket, Tracker

READY = "ready-for-agent"
COMPLETE = "<promise>TICKET COMPLETE</promise>"
MAIN = "main"


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


class Loop:
    def __init__(self, spec: int, tracker: Tracker, agent: Agent, checkout: Checkout, console: Console, config: Config):
        self.spec = spec
        self.config = config
        self.tracker = tracker
        self.agent = agent
        self.checkout = checkout
        self.console = console
        self.iteration = 0
        self.attempts: dict[int, int] = {}
        # Tickets that spent their attempts without closing. They stay open on
        # the tracker, so a rerun tries them again.
        self.left_alone: set[int] = set()

    def run(self) -> None:
        """Implements the frontier until it is empty. Raises RalphError when the run cannot end cleanly."""
        self._start()
        self.console.say(f"spec #{self.spec} on {self.branch}, base {self.base[:9]}, logs in {self.run_dir}")

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

        self.console.say(
            f"complete after {self.iteration} iterations. "
            f"Every ticket of spec #{self.spec} is closed on {self.branch} (base {self.base[:9]})."
        )
        self.console.say("nothing was pushed. Look it over, then open the pull request.")

    def _start(self) -> None:
        if not self.checkout.is_clean():
            raise RalphError("the working tree is not clean; commit or discard your changes first")
        branch = self.checkout.current_branch()
        if branch is None:
            raise RalphError("HEAD is detached; check out a branch first")

        title = self.tracker.spec_title(self.spec)
        if not self.tracker.tickets(self.spec):
            raise RalphError(
                f"spec #{self.spec} has no tickets. Split it into tickets first: sub-issues of #{self.spec} "
                f"labelled {READY}, with their blockers recorded as issue dependencies."
            )

        # The whole spec lands on one integration branch and main never gets a
        # commit. Started from any other branch, that branch is the integration branch.
        if branch == MAIN:
            branch = integration_branch(self.spec, title)
            self.checkout.switch(branch)
        self.branch = branch
        self.base = self.checkout.merge_base("HEAD", MAIN)
        self.context = prompts.RunContext(spec=self.spec, repo=self.tracker.repo, branch=branch)
        self.run_dir = runs.create(self.checkout.root)

    def _implement(self, ticket: Ticket) -> None:
        self.iteration += 1
        n = ticket.number
        attempt = self.attempts[n] = self.attempts.get(n, 0) + 1
        self.console.heading(
            f"[{self.iteration}/{self.config.max_iterations}] ticket #{n}, attempt {attempt}/{self.config.max_attempts}"
        )

        before = self.checkout.head()
        prompt = prompts.implement(
            self.context,
            self.tracker.ticket_details(n),
            fixed_point=before,
            commits=self.checkout.commits(self.base, limit=prompts.RECENT_COMMITS),
        )
        log = os.path.join(self.run_dir, f"{self.iteration:02d}-ticket-{n}.jsonl")
        final = self.agent.run(prompt, log, self.console.prose)
        self._check_checkout(f"iteration {self.iteration} (ticket #{n})")

        reason = self._not_done(final, before) or self._verify(n)
        if reason is None:
            shas = [c.short for c in reversed(self.checkout.commits(before))]
            self.tracker.close(n, f"Implemented by ralph on `{self.branch}`: {' '.join(shas)}")
            self.console.say(f"closed #{n}")
            return
        self.console.say(f"#{n} stays open, {reason}")
        if attempt >= self.config.max_attempts:
            self.left_alone.add(n)
            self.console.say(f"giving up on #{n} after {attempt} attempts; it is left alone for the rest of this run")

    def _check_checkout(self, culprit: str) -> None:
        """Stops the run unless the checkout is clean and on the integration branch, so nothing builds on a mess."""
        if not self.checkout.is_clean():
            raise RalphError(f"{culprit} left uncommitted changes; inspect them, then rerun")
        branch = self.checkout.current_branch()
        if branch != self.branch:
            where = "HEAD detached" if branch is None else f"the checkout on {branch}"
            raise RalphError(f"{culprit} left {where}, off {self.branch}; switch back, then rerun")

    def _not_done(self, final: str, before: str) -> Optional[str]:
        """Why the attempt that started at before did not finish its ticket, or None if it did."""
        if COMPLETE not in final:
            return "the agent did not report it complete"
        if self.checkout.head() == before:
            return "the agent reported it complete but made no commit"
        return None

    def _verify(self, number: int) -> Optional[str]:
        """Runs the verify command, if any. Why it failed, or None if it passed or there is none."""
        if self.config.verify is None:
            return None
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
