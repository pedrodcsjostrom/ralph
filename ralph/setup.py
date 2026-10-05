"""Set-up: makes a git repository a project, from a clone of ralph.

It writes what a project holds: the wrapper at the root and the pin. Run again
on a project that is already set up, it changes only what is missing or out of
date, so it doubles as a repair.

The pin is the release the clone is at: a tag pointing at the clone's HEAD.
A project that already has a pin keeps it; `ralph upgrade` is what moves it.
"""

import os
import stat
import textwrap
from typing import Optional

from ralph import checkout, config, pin
from ralph.checkout import Checkout
from ralph.errors import RalphError
from ralph.loop import READY
from ralph.project import RULES
from ralph.tracker import Tracker

WRAPPER = "ralph"
# Keeps the run logs, and only them, out of version control: the pin, configuration and rules are checked in.
IGNORE = os.path.join(".ralph", ".gitignore")
# The label ralph's frontier needs, as set-up creates it when the repository lacks it.
LABEL_DESCRIPTION = "Fully specified, ready for an agent to implement"
LABEL_COLOR = "0e8a16"
# A line of the wrapper's own documentation, which tells a wrapper from any other file named ralph.
WRAPPER_MARK = "This is ralph's wrapper"


class Project:
    """A project being set up: writes files under root and keeps a list of what it changed."""

    def __init__(self, root: str):
        self.root = root
        self.changes: list[str] = []

    def path(self, name: str) -> str:
        return os.path.join(self.root, name)

    def text(self, name: str) -> Optional[str]:
        try:
            with open(self.path(name), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def write(self, name: str, content: str, executable: bool = False) -> None:
        """Writes content to name unless it is already there, recording the change."""
        path = self.path(name)
        before = self.text(name)
        if before != content:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.changes.append(("created " if before is None else "refreshed ") + name)
        if executable and not os.stat(path).st_mode & stat.S_IXUSR:
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if before == content:
                self.changes.append(f"made {name} executable")

    def create(self, name: str, content: str) -> None:
        """Writes content to name only when there is no such file, so the maintainer's own stays as it is."""
        if self.text(name) is None:
            self.write(name, content)


def release(clone: str) -> str:
    """The release the ralph clone is at: the newest version tag pointing at its HEAD."""
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


def _wrapper_slot(project: Project) -> None:
    """Stops when the root already holds something named like the wrapper that is not a wrapper."""
    path = project.path(WRAPPER)
    if os.path.lexists(path) and not os.path.isfile(path):
        raise RalphError(f"{path} exists and is not a file, so the wrapper cannot go there")
    existing = project.text(WRAPPER) if os.path.isfile(path) else None
    if existing is not None and WRAPPER_MARK not in existing:
        raise RalphError(f"{path} exists and is not ralph's wrapper; move it away, then rerun")


def setup(root: str, clone: str, tracker: Tracker) -> tuple[str, list[str]]:
    """Sets the git repository at root, whose GitHub repository tracker talks to, up as a project, from the ralph
    clone at clone. Checks everything it can before it changes anything.

    Gives the pinned version and what changed, one line each.
    """
    project = Project(root)
    _wrapper_slot(project)
    existing_pin = project.text(pin.PIN)
    version = existing_pin.strip() if existing_pin else release(clone)

    if tracker.ensure_label(READY, LABEL_DESCRIPTION, LABEL_COLOR):
        project.changes.append(f"created the {READY} label on {tracker.repo}")

    with open(os.path.join(clone, "wrapper", WRAPPER), encoding="utf-8") as f:
        project.write(WRAPPER, f.read(), executable=True)
    project.create(pin.PIN, version + "\n")
    project.create(config.FILE, configuration())
    for rules in RULES.values():
        project.create(rules, "")
    project.write(IGNORE, "/runs/\n")
    return version, project.changes


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
