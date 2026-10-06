"""Set-up: makes a git repository a project, from a clone of ralph.

It writes what a project holds: the wrapper at the root, the pin, the
configuration and the project rules, the issue-tracker instructions the bundled
skills read and a section about ralph in the project's agent instructions; and
it makes sure the tracker has the label the frontier relies on. The run logs
need no ignore rule from set-up: every run keeps them out of version control
itself (see ralph.runs), set up or not.

What is ralph's (the wrapper, the issue-tracker instructions and the section)
is refreshed on every set-up; what is the project's (the pin,
the configuration and the project rules) is only created when missing. So
running it again on a project that is already set up changes nothing, or
repairs what is missing or out of date.

The pin is the release the clone is at: a version tag pointing at the clone's
HEAD, which must also be in the public repository the wrapper fetches from. A
project that already has a pin keeps it; `ralph upgrade` is what moves it.

The maintainer may name the pin instead (`--pin`), even a tag not yet pushed to
the public repository, so a project can be set up ahead of the release it will
run; set-up then warns that the wrapper cannot run until the tag is published.
"""

import os
import stat
import textwrap
from dataclasses import dataclass, field
from typing import Optional

from ralph import checkout, config, pin
from ralph.checkout import Checkout
from ralph.errors import RalphError
from ralph.project import RULES
from ralph.tracker import READY, Tracker

WRAPPER = "ralph"
# A line of the wrapper's own documentation, which tells a wrapper from any other file named ralph.
WRAPPER_MARK = "This is ralph's wrapper"
# The label the frontier relies on, as set-up creates it when the repository lacks it.
LABEL_DESCRIPTION = "Fully specified, ready for an agent to implement"
LABEL_COLOR = "0e8a16"
# Where the bundled skills look for how to use the tracker; ralph's version starts with TRACKER_MARK.
ISSUE_TRACKER = os.path.join("docs", "agents", "issue-tracker.md")
TRACKER_MARK = "<!-- Written by `ralph setup`"
# The agent instructions files, in order of preference: Claude Code reads CLAUDE.md, so it wins when both exist,
# and it is created when neither does.
INSTRUCTIONS = ("CLAUDE.md", "AGENTS.md")
SECTION_BEGIN = "<!-- ralph:begin"
SECTION_END = "<!-- ralph:end -->"

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


@dataclass
class Outcome:
    version: str
    # What set-up changed, one line each, such as "created .ralph/pin".
    changes: list[str] = field(default_factory=list)
    # What set-up chose to leave alone that the maintainer should know about.
    notes: list[str] = field(default_factory=list)


class _Files:
    """The project's files, written only when their content changes, each change recorded in the outcome."""

    def __init__(self, root: str, outcome: Outcome):
        self.root = root
        self.outcome = outcome

    def path(self, name: str) -> str:
        return os.path.join(self.root, name)

    def text(self, name: str) -> Optional[str]:
        try:
            with open(self.path(name), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def write(self, name: str, content: str, executable: bool = False) -> None:
        """Makes name hold content. A symlink is followed, so an instructions file linked to another stays linked."""
        path = self.path(name)
        before = self.text(name)
        if before != content:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.outcome.changes.append(("created " if before is None else "refreshed ") + name)
        mode = os.stat(path).st_mode
        if executable and not mode & stat.S_IXUSR:
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if before == content:
                self.outcome.changes.append(f"made {name} executable")

    def create(self, name: str, content: str) -> None:
        """Writes content to name only when there is no such file, so the project's own stays as it is."""
        if self.text(name) is None:
            self.write(name, content)


def _template(name: str) -> str:
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return f.read()


def release(clone: str) -> str:
    """The release the ralph clone is at: the newest version tag pointing at its HEAD, if it is released."""
    tags = [tag for tag in Checkout(clone).tags_at_head() if pin.VERSION.match(tag)]
    if not tags:
        raise RalphError(
            f"the ralph clone at {clone} is not at a release, so there is no version to pin: no tag points at its "
            "HEAD. Check out a release tag in the clone, or tag this commit and push the tag, then rerun"
        )
    version = pin.newest(tags)
    # The wrapper fetches the pin from the public repository, so a tag only the clone has would not run.
    source = pin.repository()
    if version not in checkout.remote_tags(source):
        raise RalphError(f"{version} is not released in {source}; push the tag there, then rerun")
    return version


def _check_wrapper_slot(files: _Files) -> None:
    """Stops when the root already holds something named like the wrapper that is not a wrapper."""
    path = files.path(WRAPPER)
    if os.path.lexists(path) and not os.path.isfile(path):
        raise RalphError(f"{path} exists and is not a file, so the wrapper cannot go there")
    if os.path.isfile(path) and WRAPPER_MARK not in (files.text(WRAPPER) or ""):
        raise RalphError(f"{path} exists and is not ralph's wrapper; move it away, then rerun")


def _instructions_file(files: _Files) -> str:
    return next((name for name in INSTRUCTIONS if os.path.exists(files.path(name))), INSTRUCTIONS[0])


def with_section(text: str, section: str, name: str) -> str:
    """text, the agent instructions in file name, with section in place of ralph's section, or at the end."""
    begin, end = text.find(SECTION_BEGIN), text.find(SECTION_END)
    if begin == -1 and end == -1:
        return text.rstrip("\n") + "\n\n" + section if text.strip() else section
    if begin == -1 or end < begin or text.count(SECTION_BEGIN) > 1 or text.count(SECTION_END) > 1:
        raise RalphError(
            f"{name} has a broken ralph section: it needs one {SECTION_BEGIN} line followed by one {SECTION_END} line; "
            "fix or remove them, then rerun"
        )
    after = text[end + len(SECTION_END) :]
    return text[:begin] + section + (after[1:] if after.startswith("\n") else after)


def explicit(version: str) -> Optional[str]:
    """Checks a version the maintainer named to pin, which may not be released yet; a warning when it is not."""
    if not pin.VERSION.match(version):
        raise RalphError(f"--pin needs a version name such as v0.1.0, not {version!r}")
    source = pin.repository()
    if version in checkout.remote_tags(source):
        return None
    return (
        f"warning: {version} is not released in {source} yet, so the wrapper cannot run until the tag is pushed there"
    )


def setup(root: str, clone: str, tracker: Tracker, version: Optional[str] = None) -> Outcome:
    """Sets the git repository at root up as a project, from the ralph clone at clone. tracker talks to the
    project's GitHub repository. version, when given, is the pin, released or not; otherwise the pin is the release
    the clone is at. Checks everything it can before it changes anything."""
    files = _Files(root, Outcome(""))
    _check_wrapper_slot(files)
    existing_pin = files.text(pin.PIN)
    if version is not None:
        warning = explicit(version)
        if existing_pin and existing_pin.strip() != version:
            raise RalphError(
                f"the project is pinned to {existing_pin.strip()} and set-up never moves a pin; move it with "
                f"`./ralph upgrade {version}`, or rerun without --pin"
            )
        if warning:
            files.outcome.notes.append(warning)
        files.outcome.version = version
    else:
        files.outcome.version = existing_pin.strip() if existing_pin else release(clone)
    instructions = _instructions_file(files)
    agent_instructions = with_section(files.text(instructions) or "", _template("agent-instructions.md"), instructions)

    if tracker.ensure_label(READY, LABEL_DESCRIPTION, LABEL_COLOR):
        files.outcome.changes.append(f"created the {READY} label on {tracker.repo}")

    with open(os.path.join(clone, "wrapper", WRAPPER), encoding="utf-8") as f:
        files.write(WRAPPER, f.read(), executable=True)
    files.create(pin.PIN, files.outcome.version + "\n")
    files.create(config.FILE, configuration())
    for rules in RULES.values():
        files.create(rules, "")

    existing_tracker = files.text(ISSUE_TRACKER)
    if existing_tracker is None or existing_tracker.startswith(TRACKER_MARK):
        files.write(ISSUE_TRACKER, _template("issue-tracker.md"))
    else:
        files.outcome.notes.append(f"kept {ISSUE_TRACKER}, which ralph did not write")
    files.write(instructions, agent_instructions)
    return files.outcome


def configuration() -> str:
    """The configuration file a new project starts with: every key commented out at its default, with its meaning."""
    lines = [
        "# ralph's configuration for this project: one `key = value` per line, read by every run.",
        "# Each key below is commented out, so its default applies; `./ralph help` documents them all.",
        "# RALPH_<KEY> in the environment overrides a key for one run, as in RALPH_MAX_ATTEMPTS=1.",
    ]
    for key in config.KEYS:
        lines += ["", textwrap.fill(key.meaning, 100, initial_indent="# ", subsequent_indent="# ")]
        lines.append(f"# {key.name} = {key.default}".rstrip())
    return "\n".join(lines) + "\n"
