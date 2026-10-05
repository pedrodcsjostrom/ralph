"""Agent: the only module that launches Claude Code."""

import json
import subprocess
import threading
from typing import Callable

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


class Agent:
    def __init__(self, directory: str):
        self.directory = directory

    def run(self, prompt: str, log_path: str, on_prose: Callable[[str], None]) -> str:
        """Runs one headless iteration in a fresh context window and returns the agent's final message.

        The prompt goes in on stdin, which has no length limit, unlike an argument. Every event the
        agent emits is written to log_path, and the prose in them is passed to on_prose as it arrives.
        """
        try:
            agent = subprocess.Popen(
                ["claude"] + HEADLESS + PERMISSIONS,
                cwd=self.directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
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
                    if event.get("type") == "result":
                        final = event.get("result") or ""
        finally:
            agent.stdout.close()
            agent.wait()
            feeder.join()
        return final
