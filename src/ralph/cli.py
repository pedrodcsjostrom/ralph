"""The command line: parses arguments, checks the machine, and hands over to a command."""

import argparse
import os
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import NamedTuple, Optional

from ralph import (
    CLONE,
    agent,
    checkout,
    draft,
    manual,
    pin,
    progress,
    project,
    prompts,
    runs,
    setup,
    skill_sync,
    tracker,
)
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.config import Config
from ralph.console import Console
from ralph.errors import AlreadyReported, RalphError
from ralph.loop import Loop
from ralph.record import RunRecord
from ralph.tracker import Tracker


def _issue_number(value: str) -> int:
    number = value[1:] if value.startswith("#") else value
    if not number.isdigit() or int(number) < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not an issue number")
    return int(number)


def _parser() -> argparse.ArgumentParser:
    """The command line. Every command's description is also its entry in `ralph help` (see ralph.manual)."""
    parser = argparse.ArgumentParser(
        prog="ralph",
        description="Implements a spec unattended, one ticket at a time.",
        epilog="Run `ralph help` for every command and configuration key.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.required = True

    run = commands.add_parser(
        "run",
        help="implement a spec's tickets unattended",
        description="Implements the spec's tickets one at a time on its integration branch, created from the main "
        "branch as spec/<number>-<title> when started there, then reviews the work and implements the fix tickets "
        "the review raises until a review round is clean. Nothing is pushed. Stops early, saying why, when a "
        "budget is spent or nothing more can be implemented; rerun to carry on.",
    )
    run.add_argument("spec", metavar="<spec>", type=_issue_number, help="the spec's issue number")
    run.set_defaults(handler=_run)

    watch = commands.add_parser(
        "watch",
        help="watch one iteration in an interactive session",
        description="Opens an interactive Claude Code session on the ticket an unattended run would implement next, "
        "on the same integration branch and with the same prompt, which also tells the agent you are there to "
        "answer questions. Closes nothing: when the session ends, close the ticket yourself once you are happy "
        "with its commits. Use it to watch one iteration before leaving a run unattended.",
    )
    watch.add_argument("spec", metavar="<spec>", type=_issue_number, help="the spec's issue number")
    watch.set_defaults(handler=_watch)

    split = commands.add_parser(
        "split",
        help="split a spec into tickets in an interactive session",
        description="Opens an interactive Claude Code session that splits the spec into tickets with the bundled "
        "ralph:to-tickets skill, agreeing the breakdown with you before it opens any. The tickets are what a run "
        "implements: sub-issues of the spec labelled ready-for-agent, with their blockers recorded as issue "
        "dependencies. Run it on a spec before its first run.",
    )
    split.add_argument("spec", metavar="<spec>", type=_issue_number, help="the spec's issue number")
    split.set_defaults(handler=_split)

    publish = commands.add_parser(
        "publish",
        help="push the integration branch and open the pull request",
        description="Pushes the latest run's integration branch to origin and opens a pull request from it against "
        "the main branch, titled after the spec, with the run's pull request draft as its body; the draft covers "
        "every run of the spec on that branch. The only command that takes work off this machine. "
        "Refuses when the latest run did not end cleanly; --force publishes it anyway.",
    )
    publish.add_argument(
        "--force", action="store_true", help="publish the latest run even though it did not end cleanly"
    )
    publish.set_defaults(handler=_publish)

    upgrade = commands.add_parser(
        "upgrade",
        help="move the project's pin to a newer ralph version",
        description="Moves the project's pin (.ralph/pin) to the newest released ralph version, or to the named one, "
        "and reports the versions it moved from and to. Commit the changed pin to upgrade every runner.",
    )
    upgrade.add_argument("version", metavar="<version>", nargs="?", help="the release tag to pin (default: the newest)")
    upgrade.set_defaults(handler=_upgrade)

    help_ = commands.add_parser(
        "help",
        help="document every command and configuration key",
        description="Shows this help: every command and configuration key of the running version.",
    )
    help_.set_defaults(handler=lambda args, console: _help(commands.choices, console))

    setup_ = commands.add_parser(
        "setup",
        help="(maintainer) set a project up for ralph",
        description="Maintainer only, run from a clone of ralph. Sets the git repository holding <directory> "
        "(default: the current directory) up as a project: the wrapper at its root, the pin, the configuration "
        "and empty project rules in .ralph, the "
        "ready-for-agent label on its GitHub repository, the issue-tracker instructions the bundled skills read "
        "(docs/agents/issue-tracker.md) and a short section about ralph in its CLAUDE.md, or AGENTS.md when only "
        "that exists. The pin is the release the clone is at, the version tag on its HEAD; a project that already "
        "has a pin keeps it. With --pin <tag> the pin is that version instead, even one not yet released, so a "
        "project can be set up ahead of its release; the wrapper cannot run until the tag is pushed to the repository "
        "it fetches from. Running it again repairs what is missing and refreshes what is ralph's, leaving the "
        "configuration and project rules as they are. Nothing is committed.",
    )
    setup_.add_argument(
        "directory", metavar="<directory>", nargs="?", default=".", help="a directory of the project to set up"
    )
    setup_.add_argument(
        "--pin",
        metavar="<tag>",
        dest="version",
        help="pin this version instead of the release the clone is at; it may be a tag not yet released",
    )
    setup_.set_defaults(handler=_setup, maintainer=True)

    sync = commands.add_parser(
        "sync-skills",
        help="(maintainer) regenerate the bundled skills from a local skills directory",
        description="Maintainer only, run from a clone of ralph. Overwrites the bundled skills in this clone's "
        "plugin/ directory with copies of " + ", ".join(skill_sync.BUNDLED) + " from the skills directory "
        "(default: ~/.claude/skills), repointing references between them to their ralph: names, recording where "
        "each came from and carrying the upstream license notice. References to skills that are not bundled are "
        "reported. Review the result as a diff; never edit the bundled skills by hand.",
    )
    sync.add_argument(
        "skills",
        metavar="<skills-dir>",
        nargs="?",
        default="~/.claude/skills",
        help="the skills directory to copy from (default: ~/.claude/skills)",
    )
    sync.set_defaults(handler=_sync_skills, maintainer=True)
    return parser


def _help(commands: Mapping[str, argparse.ArgumentParser], console: Console) -> int:
    console.document(manual.text(commands))
    return 0


def require_tools(*tools: ModuleType) -> None:
    """Stops with every one of tools (checkout, tracker, agent) that is missing or not logged in."""
    found = [problem for tool in tools for problem in tool.problems()]
    if found:
        raise RalphError("cannot start:\n" + "\n".join("  - " + p for p in found))


class _Session(NamedTuple):
    """What every command that launches agents needs: the project, its configuration, its tracker and an agent."""

    root: str
    config: Config
    tracker: Tracker
    agent: Agent


def _session(console: Console) -> _Session:
    """Checks the machine, the configuration and that an agent resolves the bundled skills, before any change."""
    require_tools(checkout, tracker, agent)
    root = project.root(os.environ)
    config = Config.load(root, os.environ)
    claude = Agent(root, config.agent_flags)
    with console.waiting("Claude Code: checking it resolves the bundled skills"):
        claude.check()
    return _Session(root, config, Tracker(root, console.progress), claude)


def _loop(spec: int, console: Console) -> Loop:
    """The loop for spec in the project, once the machine and the configuration are known to be fit."""
    found = _session(console)
    return Loop(spec, found.tracker, found.agent, Checkout(found.root), console, found.config)


def _run(args: argparse.Namespace, console: Console) -> int:
    _loop(args.spec, console).run()
    return 0


def _watch(args: argparse.Namespace, console: Console) -> int:
    _loop(args.spec, console).watch()
    return 0


def _split(args: argparse.Namespace, console: Console) -> int:
    found = _session(console)
    title = found.tracker.spec_title(args.spec)
    console.say(f"splitting spec #{args.spec} into tickets in an interactive session")
    status = found.agent.interactive(prompts.split(args.spec, title, found.tracker.repo))
    tickets = len(found.tracker.tickets(args.spec))
    count = f"{tickets} ticket{'' if tickets == 1 else 's'}"
    if status != 0:
        raise RalphError(
            f"the session splitting spec #{args.spec} ended with exit status {status}; spec #{args.spec} has {count}"
        )
    if not tickets:
        raise RalphError(f"the session ended and spec #{args.spec} still has no tickets")
    console.say(f"spec #{args.spec} has {count}; implement them with `ralph run {args.spec}`")
    return 0


def _publish(args: argparse.Namespace, console: Console) -> int:
    require_tools(checkout, tracker)
    repo = Checkout(project.root(os.environ))
    config = Config.load(repo.root, os.environ)
    run = runs.latest(repo.root)
    if run is None:
        raise RalphError("there is no run to publish in this project; start one with `ralph run <spec>`")
    path = os.path.join(run, draft.FILE)
    if not os.path.isfile(path):
        raise RalphError(f"the latest run, {run}, left no pull request draft to publish ({path} is missing)")
    try:
        record = RunRecord.load(run)
    except (OSError, ValueError) as e:
        raise RalphError(f"the latest run, {run}, left no readable record of how it ended: {e}") from e
    if not record.ended_cleanly and not args.force:
        reason = record.reason or "it never finished"
        raise RalphError(
            f"the latest run, {run}, did not end cleanly, so it is not published:\n"
            + "\n".join(("  " + line).rstrip() for line in reason.splitlines())
            + "\nrerun to finish the spec, or publish it as it is with `ralph publish --force`"
        )
    with open(path, encoding="utf-8") as f:
        body = f.read()
    tracker_ = Tracker(repo.root, console.progress)
    title = tracker_.spec_title(record.spec)
    with console.waiting(f"pushing {record.branch}"):
        repo.push(record.branch)
    console.say(f"pushed {record.branch}")
    url = tracker_.open_pull_request(config.main_branch, record.branch, title, body)
    console.say(f"opened the pull request {url}")
    return 0


def _sync_skills(args: argparse.Namespace, console: Console) -> int:
    plugin = os.path.join(CLONE, "plugin")
    unbundled = skill_sync.sync(args.skills, plugin)
    console.say(f"bundled {', '.join(skill_sync.BUNDLED)} into {plugin}")
    if unbundled:
        console.say(
            "bundled skills refer to skills that are not bundled:\n"
            + "\n".join(f"  {path}: {reference}" for path, reference in unbundled)
        )
    return 0


def _setup(args: argparse.Namespace, console: Console) -> int:
    require_tools(checkout, tracker)
    root = Checkout.at(os.path.abspath(args.directory)).root
    outcome = setup.setup(root, CLONE, Tracker(root, console.progress), args.version)
    for note in outcome.notes:
        console.say(note)
    if outcome.changes:
        console.say(f"set up {root} for ralph {outcome.version}:\n" + "\n".join("  " + c for c in outcome.changes))
        console.say("review and commit the changes, then split a spec into tickets with `./ralph split <spec>`")
    else:
        console.say(f"{root} is already set up for ralph {outcome.version}; nothing changed")
    return 0


def _upgrade(args: argparse.Namespace, console: Console) -> int:
    old, new = pin.upgrade(project.root(os.environ), args.version)
    if new != old:
        console.say(f"moved the pin from {old} to {new}")
    elif args.version is None:
        console.say(f"already on the newest version, {new}; nothing changed")
    else:
        console.say(f"already on {new}; nothing changed")
    return 0


def main(argv: list[str], console: Optional[Console] = None) -> int:
    console = console or Console()
    args = _parser().parse_args(argv)
    try:
        try:
            console.progress.interval = progress.interval(os.environ)
        except ValueError as e:
            raise RalphError(str(e)) from None
        return args.handler(args, console)
    except AlreadyReported as e:
        return e.status
    except RalphError as e:
        console.error(str(e))
        return 1
    except KeyboardInterrupt:
        console.error("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
