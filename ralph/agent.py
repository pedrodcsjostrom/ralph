"""Agent: the only module that launches Claude Code."""

import json
import os
import subprocess
import threading
from typing import Callable, Optional

from ralph import proc
from ralph.errors import RalphError

# Agents' commits and pull requests carry no attribution trailer.
SETTINGS = json.dumps({"attribution": {"commit": "", "pr": ""}})

HEADLESS = ["--print", "--verbose", "--output-format", "stream-json", "--settings", SETTINGS]
PERMISSIONS = ["--permission-mode", "auto"]


def problems() -> list[str]:
    """What stops Claude Code from being used, if anything."""
    if not proc.on_path("claude"):
        return ["Claude Code (claude) is not on PATH; install it from https://claude.com/claude-code"]
    if not proc.succeeds(["claude", "auth", "status"]):
        return ["Claude Code (claude) is not logged in; run `claude auth login`"]
    return []


def _texts(event: dict) -> list[str]:
    """The prose in an assistant event."""
    if event.get("type") != "assistant":
        return []
    content = (event.get("message") or {}).get("content") or []
    return [
        part["text"] for part in content if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ]


# What an agent tool call is about, by tool: the first of these input fields that is set.
_TOOL_SUBJECT = ("description", "skill", "file_path", "notebook_path", "pattern", "url", "query", "command", "prompt")


def activity(event: dict, directory: str = "") -> Optional[str]:
    """What the agent is doing, judging by one of its events, such as "Bash: Run the tests"; None if it does not say.

    Paths under directory are shown relative to it.
    """
    kind = event.get("type")
    if kind == "system":
        return "thinking" if event.get("subtype") == "thinking_tokens" else None
    if kind not in ("assistant", "user"):
        return None
    content = (event.get("message") or {}).get("content") or []
    found = None
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_use":
            name = str(part.get("name") or "a tool")
            given = part.get("input") if isinstance(part.get("input"), dict) else {}
            subject = next((given[k] for k in _TOOL_SUBJECT if isinstance(given.get(k), str) and given[k].strip()), "")
            if subject and directory and os.path.isabs(subject) and subject.startswith(directory.rstrip("/") + "/"):
                subject = os.path.relpath(subject, directory)
            found = f"{name}: {subject}" if subject else name
        elif part.get("type") == "tool_result":
            # The tool is done; the agent is reading what it said.
            found = "thinking"
        elif part.get("type") == "thinking":
            found = "thinking"
        elif part.get("type") == "text":
            found = "writing"
    return found


class Agent:
    def __init__(self, directory: str):
        self.directory = directory

    def run(
        self,
        prompt: str,
        log_path: str,
        on_prose: Callable[[str], None],
        on_activity: Callable[[Optional[str]], None] = lambda _: None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Runs one headless iteration in a fresh context window and returns the agent's final message.

        The prompt goes in on stdin, which has no length limit, unlike an argument. Every event the
        agent emits is written to log_path, the prose in them is passed to on_prose as it arrives, and
        what the agent is doing (see activity) to on_activity whenever it changes. Lines the agent
        writes to its standard error go to on_stderr if given, else straight to ralph's.
        """
        try:
            agent = subprocess.Popen(
                ["claude"] + HEADLESS + PERMISSIONS,
                cwd=self.directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None if on_stderr is None else subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as e:
            raise RalphError(f"could not start Claude Code: {e}") from e

        def feed() -> None:
            try:
                agent.stdin.write(prompt)
                agent.stdin.close()
            except BrokenPipeError:
                pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        if on_stderr is not None:

            def relay() -> None:
                for line in agent.stderr:
                    on_stderr(line)

            relayer = threading.Thread(target=relay, daemon=True)
            relayer.start()

        on_activity("starting Claude Code")

        final = ""
        try:
            with open(log_path, "w", encoding="utf-8") as log:
                for line in agent.stdout:
                    # A real run prints some lines that are not events; only events are kept.
                    if not line.startswith("{"):
                        continue
                    log.write(line)
                    log.flush()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    for text in _texts(event):
                        on_prose(text)
                    doing = activity(event, self.directory)
                    if doing is not None:
                        on_activity(doing)
                    if event.get("type") == "result":
                        final = event.get("result") or ""
        finally:
            agent.stdout.close()
            agent.wait()
            feeder.join()
            if on_stderr is not None:
                relayer.join()
                agent.stderr.close()
        return final
