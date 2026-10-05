"""The command line: parses arguments, checks the machine, and hands over to a command."""

import argparse
import os
import sys
from typing import Optional

from ralph import agent, checkout, pin, tracker
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.console import Console
from ralph.errors import RalphError
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
    return parser


def require_tools() -> None:
    """Stops with every required tool that is missing or not logged in."""
    found = checkout.problems() + tracker.problems() + agent.problems()
    if found:
        raise RalphError("cannot start:\n" + "\n".join("  - " + p for p in found))


def _run(args: argparse.Namespace, console: Console) -> int:
    require_tools()
    repo = Checkout.at(os.getcwd())
    Loop(args.spec, Tracker(repo.root), Agent(repo.root), repo, console).run()
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
    except RalphError as e:
        console.error(str(e))
        return 1
    except KeyboardInterrupt:
        console.error("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
