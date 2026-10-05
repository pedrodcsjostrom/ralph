"""Loop: the deterministic core of a run.

It decides which ticket is next, whether it is done and when to stop. It
knows Tracker, Agent and Checkout only by what they answer and perform, never
by how. A run keeps no state of its own between invocations: everything it
needs is read from the tracker and the integration branch.
"""

import os
import re
from typing import Iterable, List, Optional, Set

from ralph import prompts, runs
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.console import Console
from ralph.errors import RalphError
from ralph.tracker import Ticket, Tracker

READY = "ready-for-agent"
COMPLETE = "<promise>TICKET COMPLETE</promise>"
MAIN = "main"


def frontier(tickets: Iterable[Ticket], leave_alone: Iterable[int] = ()) -> List[Ticket]:
    """The tickets that are open, ready for an agent and not blocked, lowest number first."""
    skip = set(leave_alone)
    return sorted(
        (t for t in tickets if t.is_open and READY in t.labels and t.open_blockers == 0 and t.number not in skip),
        key=lambda t: t.number,
    )


def integration_branch(spec: int, title: str) -> str:
    """The branch a spec lands on when a run starts from the main branch, e.g. spec/1-widget-sorting."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).lstrip("-")[:40].rstrip("-")
    return "spec/%d-%s" % (spec, slug) if slug else "spec/%d" % spec


class Loop:
    def __init__(self, spec: int, tracker: Tracker, agent: Agent, checkout: Checkout, console: Console):
        self.spec = spec
        self.tracker = tracker
        self.agent = agent
        self.checkout = checkout
        self.console = console
        self.iteration = 0
        # Tickets an attempt did not close this run. They stay open on the
        # tracker, so a rerun tries them again.
        self.left_alone: Set[int] = set()

    def run(self) -> None:
        """Implements the frontier until it is empty. Raises RalphError when the run cannot end cleanly."""
        self._start()
        self.console.say(
            "spec #%d on %s, base %s, logs in %s" % (self.spec, self.branch, self.base[:9], self.run_dir)
        )

        while True:
            ready = frontier(self.tracker.tickets(self.spec), self.left_alone)
            if not ready:
                break
            self._implement(ready[0])

        still_open = [t for t in self.tracker.tickets(self.spec) if t.is_open]
        if still_open:
            raise RalphError(
                "stopping, these tickets are open and nothing on the frontier can be implemented:\n"
                + "\n".join("#%d %s" % (t.number, t.title) for t in sorted(still_open, key=lambda t: t.number))
            )

        self.console.say(
            "complete after %d iterations. Every ticket of spec #%d is closed on %s (base %s)."
            % (self.iteration, self.spec, self.branch, self.base[:9])
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
                "spec #%d has no tickets. Split it into tickets first: sub-issues of #%d labelled %s, "
                "with their blockers recorded as issue dependencies." % (self.spec, self.spec, READY)
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
        self.console.heading("[%d] ticket #%d" % (self.iteration, n))

        before = self.checkout.head()
        prompt = prompts.implement(
            self.context,
            self.tracker.ticket_details(n),
            fixed_point=before,
            commits=self.checkout.commits(self.base, limit=prompts.RECENT_COMMITS),
        )
        log = os.path.join(self.run_dir, "%02d-ticket-%d.jsonl" % (self.iteration, n))
        final = self.agent.run(prompt, log, self.console.prose)

        reason = self._not_done(final, before)
        if reason is None:
            shas = [c.short for c in reversed(self.checkout.commits(before))]
            self.tracker.close(n, "Implemented by ralph on `%s`: %s" % (self.branch, " ".join(shas)))
            self.console.say("closed #%d" % n)
        else:
            self.left_alone.add(n)
            self.console.say("#%d stays open, %s; leaving it alone for the rest of this run" % (n, reason))

    def _not_done(self, final: str, before: str) -> Optional[str]:
        """Why the attempt that started at before did not finish its ticket, or None if it did."""
        if COMPLETE not in final:
            return "the agent did not report it complete"
        if self.checkout.head() == before:
            return "the agent reported it complete but made no commit"
        return None
