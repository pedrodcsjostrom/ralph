"""Manual: the text of `ralph help`, the documentation of every command and configuration key of the running version.

It is built from the command line's own parsers and from ralph.config.KEYS, so
a new command or key is documented by being added there. A command marks
itself as for maintainers with `set_defaults(maintainer=True)`.
"""

import argparse
import textwrap
from collections.abc import Mapping

from ralph import agent, config, pin, progress, project

WIDTH = 100

INTRO = """\
ralph implements a spec unattended, one ticket at a time, on a single integration branch that you
then review and open a pull request from. Run it through the project's wrapper, `./ralph`, which
runs the version the project is pinned to; every command acts on the wrapper's project, wherever
it is run from."""

ENVIRONMENT = (
    ("RALPH_REPOSITORY", f"where ralph's releases are listed and fetched from (default: {pin.REPOSITORY})"),
    ("RALPH_CACHE", "the per-user cache of fetched versions (default: $XDG_CACHE_HOME/ralph, or ~/.cache/ralph)"),
    ("RALPH_PROJECT", "the project to act on; the wrapper sets it to its own directory"),
    (
        progress.INTERVAL_VARIABLE,
        f"seconds between progress lines while ralph waits, off a terminal (default: {progress.INTERVAL:g})",
    ),
)


def _paragraph(text: str, indent: str) -> str:
    return textwrap.fill(" ".join(text.split()), WIDTH, initial_indent=indent, subsequent_indent=indent)


def _command(name: str, parser: argparse.ArgumentParser) -> list[str]:
    usage = " ".join(parser.format_usage().split()[1:]).replace(" [-h]", "")
    return [f"  {usage}", _paragraph(parser.description or "", "      "), ""]


def text(commands: Mapping[str, argparse.ArgumentParser]) -> str:
    """The help for commands, the subcommand parsers by name."""
    runner = [n for n, p in commands.items() if not p.get_default("maintainer")]
    maintainer = [n for n, p in commands.items() if p.get_default("maintainer")]
    lines = [INTRO, "", "Commands", ""]
    for name in runner:
        lines += _command(name, commands[name])

    lines += [
        "Configuration",
        "",
        _paragraph(
            f"The project's checked-in {config.FILE} holds one `key = value` per line; blank lines and lines "
            "starting with # are ignored. The environment variable beside each key overrides it for one run. "
            "An empty value, in the file or the environment, means the default. An unknown key or a malformed "
            "value stops the run before it starts.",
            "  ",
        ),
        "",
    ]
    width = max(len(k.name) for k in config.KEYS) + 2
    env_width = max(len(k.env) for k in config.KEYS) + 2
    lines.append(f"  {'key':<{width}}{'environment':<{env_width}}default")
    for key in config.KEYS:
        lines.append(f"  {key.name:<{width}}{key.env:<{env_width}}{key.default or '(none)'}")
        lines.append(_paragraph(key.meaning, "      "))
    lines.append("")

    lines += [
        "Project rules",
        "",
        _paragraph(
            f"Text in {project.RULES['implement']} is added to ralph's instructions for every implementing "
            f"iteration, and text in {project.RULES['review']} to those for every review. They add to ralph's "
            "instructions and never replace them; either file may be missing or empty.",
            "  ",
        ),
        "",
        "Agents",
        "",
        _paragraph(
            "Every agent ralph launches loads ralph's bundled skills (" + ", ".join(agent.SKILLS) + ") for its "
            "session only and runs at project scope: it sees what the project has checked in, the bundled skills "
            "and the project rules, but none of your personal Claude Code settings, instructions, memory, skills "
            "or MCP servers. It still uses your Claude Code login. A run first checks, at no cost, that Claude "
            "Code resolves the bundled skills. What Claude Code cannot exclude is listed in "
            "docs/adr/0002-agents-run-at-project-scope-only.md in ralph's repository.",
            "  ",
        ),
        "",
        "Environment",
        "",
    ]
    for name, meaning in ENVIRONMENT:
        lines += [f"  {name}", _paragraph(meaning, "      ")]
    lines.append("")

    if maintainer:
        lines += ["Maintainer commands", ""]
        for name in maintainer:
            lines += _command(name, commands[name])
    return "\n".join(lines).rstrip() + "\n"
