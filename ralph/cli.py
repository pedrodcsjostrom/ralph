"""The command line: parses arguments, checks the machine, and hands over to a command."""

import argparse
import os
import sys
from typing import Optional

from ralph import agent, checkout, pin, skill_sync, tracker
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.config import Config
from ralph.console import Console
from ralph.errors import RalphError, Reported
from ralph.loop import Loop
from ralph.tracker import Tracker


def _issue_number(value: str) -> int:
    number = value[1:] if value.startswith("#") else value
    if not number.isdigit() or int(number) < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not an issue number")
    return int(number)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ralph", description="Implements a spec unattended, one ticket at a time.")
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.required = True

    run = commands.add_parser("run", help="implement a spec's tickets unattended")
    run.add_argument("spec", type=_issue_number, help="the spec's issue number")
    run.set_defaults(handler=_run)

    upgrade = commands.add_parser(
        "upgrade",
        help="move the project's pin to a newer ralph version",
        description="Moves the project's pin (.ralph/pin) to the newest released ralph version, or to the named one, "
        "and reports the versions it moved from and to. Commit the changed pin to upgrade every runner.",
    )
    upgrade.add_argument("version", nargs="?", help="the release tag to pin (default: the newest)")
    upgrade.set_defaults(handler=_upgrade)

    sync = commands.add_parser(
        "sync-skills",
        help="(maintainer) regenerate the bundled skills from a local skills directory",
        description="Maintainer only, run from a clone of ralph. Overwrites the bundled skills in this clone's "
        "plugin/ directory with copies of " + ", ".join(skill_sync.BUNDLED) + " from the skills directory, "
        "repointing references between them to their ralph: names, recording where each came from and carrying "
        "the upstream license notice. References to skills that are not bundled are reported. Review the result "
        "as a diff; never edit the bundled skills by hand.",
    )
    sync.add_argument(
        "skills",
        nargs="?",
        default="~/.claude/skills",
        help="the skills directory to copy from (default: ~/.claude/skills)",
    )
    sync.set_defaults(handler=_sync_skills)
    return parser


def require_tools() -> None:
    """Stops with every required tool that is missing or not logged in."""
    found = checkout.problems() + tracker.problems() + agent.problems()
    if found:
        raise RalphError("cannot start:\n" + "\n".join("  - " + p for p in found))


def _run(args: argparse.Namespace, console: Console) -> int:
    config = Config.from_env(os.environ)
    require_tools()
    repo = Checkout.at(os.getcwd())
    Loop(args.spec, Tracker(repo.root), Agent(repo.root), repo, console, config).run()
    return 0


def _sync_skills(args: argparse.Namespace, console: Console) -> int:
    plugin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin")
    unbundled = skill_sync.sync(args.skills, plugin)
    console.say(f"bundled {', '.join(skill_sync.BUNDLED)} into {plugin}")
    if unbundled:
        console.say(
            "bundled skills refer to skills that are not bundled:\n"
            + "\n".join(f"  {path}: {reference}" for path, reference in unbundled)
        )
    return 0


def _upgrade(args: argparse.Namespace, console: Console) -> int:
    old, new = pin.upgrade(Checkout.at(os.getcwd()).root, args.version)
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
        return args.handler(args, console)
    except Reported as e:
        return e.status
    except RalphError as e:
        console.error(str(e))
        return 1
    except KeyboardInterrupt:
        console.error("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
