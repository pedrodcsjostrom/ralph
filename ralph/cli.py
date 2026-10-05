"""The command line: parses arguments, checks the machine, and hands over to a command."""

import argparse
import os
import sys
from typing import Optional

from ralph import agent, checkout, tracker
from ralph.agent import Agent
from ralph.checkout import Checkout
from ralph.config import Config
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
