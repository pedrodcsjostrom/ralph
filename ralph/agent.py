"""Agent: the only module that launches Claude Code."""

import json
import subprocess
import threading
from collections.abc import Sequence
from typing import Callable

from ralph import proc
from ralph.errors import RalphError

# Agents' commits and pull requests carry no attribution trailer.
SETTINGS = json.dumps({"attribution": {"commit": "", "pr": ""}})

# Every launch, headless or interactive, gets these.
COMMON = ["--settings", SETTINGS, "--permission-mode", "auto"]
HEADLESS = ["--print", "--verbose", "--output-format", "stream-json"]


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
    def __init__(self, directory: str, flags: Sequence[str] = ()):
        self.directory = directory
        # The project's extra flags, after ralph's own so they can refine them.
        self.flags = list(flags)

    def _command(self, mode: Sequence[str]) -> list[str]:
        """The claude command line for a launch in mode, without the prompt."""
        return ["claude"] + list(mode) + COMMON + self.flags

    def interactive(self, prompt: str) -> int:
        """Opens an interactive session on the runner's terminal, starting from prompt. Returns its exit status.

        Claude Code takes an interactive session's first prompt as an argument; stdin is the terminal.
        """
        try:
            return subprocess.run(self._command([]) + [prompt], cwd=self.directory).returncode
        except OSError as e:
            raise RalphError(f"could not start Claude Code: {e}") from e

    def run(self, prompt: str, log_path: str, on_prose: Callable[[str], None]) -> str:
        """Runs one headless iteration in a fresh context window and returns the agent's final message.

        The prompt goes in on stdin, which has no length limit, unlike an argument. Every event the
        agent emits is written to log_path, and the prose in them is passed to on_prose as it arrives.
        """
        try:
            agent = subprocess.Popen(
                self._command(HEADLESS),
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
