"""Agent: the only module that launches Claude Code.

Every launch, headless or interactive, runs at project scope with the bundled skills
(ADR 0001, ADR 0002): the `ralph` plugin of this copy of ralph is loaded for that session
only, and the runner's user-level settings, instructions, memory, skills and MCP servers are
switched off. Authentication still comes from the runner's login. What Claude Code cannot
switch off is listed in docs/adr/0002-agents-run-at-project-scope-only.md.
"""

import json
import os
import re
import subprocess
import threading
from collections.abc import Mapping, Sequence
from typing import Callable, Optional

from ralph import proc, skill_sync
from ralph.errors import RalphError

# The bundled skills, loaded for each session only and invoked under the `ralph:` namespace.
PLUGIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin")
SKILLS = sorted("ralph:" + name for name in skill_sync.BUNDLED)

HEADLESS = ["--print", "--verbose", "--output-format", "stream-json", "--no-session-persistence"]

# Variables a Claude Code session sets for the commands it runs. When ralph is started from
# inside such a session, its agents must not take themselves for part of it.
SESSION_VARIABLES = re.compile(
    r"CLAUDECODE|CLAUDE_PID|CLAUDE_CODE_(ENTRYPOINT|SESSION_ID|CHILD_SESSION|SESSION_ATTENDED|EXECPATH|MESSAGING_.*)"
)

# Characters Claude Code reads as glob syntax in claudeMdExcludes.
GLOB = re.compile(r"([*?\[\]{}()!\\])")


def environment(env: Mapping[str, str]) -> dict[str, str]:
    """The environment every claude process gets: env without the variables of a Claude Code session."""
    return {k: v for k, v in env.items() if not SESSION_VARIABLES.fullmatch(k)}


def settings(project: str) -> str:
    """The --settings JSON for agents working in the project directory.

    Claude Code counts the instruction files in the directories above the project (~/AGENTS.md,
    ~/CLAUDE.md, a parent's .claude/rules) as project memory, so --setting-sources does not drop
    them. They are excluded here, for every ancestor, while the project's own stay.
    """
    excludes = []
    directory = os.path.realpath(project)
    while directory != os.path.dirname(directory):
        directory = os.path.dirname(directory)
        escaped = GLOB.sub(r"\\\1", directory.rstrip("/"))
        excludes += [escaped + "/*.md", escaped + "/.claude/**"]
    return json.dumps(
        {
            # Agents' commits and pull requests carry no attribution trailer.
            "attribution": {"commit": "", "pr": ""},
            "autoMemoryEnabled": False,
            "claudeMdExcludes": excludes,
        }
    )


def problems() -> list[str]:
    """What stops Claude Code from being used, if anything."""
    if not proc.on_path("claude"):
        return ["Claude Code (claude) is not on PATH; install it from https://claude.com/claude-code"]
    if not proc.succeeds(["claude", "auth", "status"], env=environment(os.environ)):
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


def _init(output: str) -> Optional[dict]:
    """The init event among a headless run's output lines, if there is one."""
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
            return event
    return None


class Agent:
    def __init__(self, directory: str, flags: Sequence[str] = ()):
        self.directory = directory
        self.scope = [
            "--plugin-dir",
            PLUGIN,
            "--setting-sources",
            "project",
            "--strict-mcp-config",
            "--permission-mode",
            "auto",
            "--settings",
            settings(directory),
        ]
        # The project's extra flags, after ralph's own so they can refine them.
        self.flags = list(flags)

    def _command(self, mode: Sequence[str], arguments: Sequence[str] = ()) -> list[str]:
        """The claude command line for a launch in mode, with arguments as its positional arguments.

        The arguments follow `--`, so a project flag that takes several values cannot swallow them.
        """
        return ["claude"] + list(mode) + self.scope + self.flags + (["--"] + list(arguments) if arguments else [])

    def check(self) -> None:
        """Stops unless an agent, launched as every iteration is, resolves the bundled skills at project scope.

        `/context` makes no model call, so the check is free and takes seconds.
        """
        found = proc.completed(self._command(HEADLESS, ["/context"]), cwd=self.directory, env=environment(os.environ))
        init = _init(found.stdout)
        if found.returncode != 0 or init is None:
            detail = found.stderr.strip() or found.stdout.strip() or f"exit status {found.returncode}"
            raise RalphError(
                f"Claude Code could not start with ralph's launch flags and the project's agent_flags:\n{detail}"
            )
        missing = [skill for skill in SKILLS if skill not in (init.get("skills") or [])]
        if missing:
            raise RalphError(
                f"Claude Code cannot resolve the bundled skill{'s' if len(missing) > 1 else ''} {', '.join(missing)} "
                f"from the plugin at {PLUGIN}; this copy of ralph is incomplete (if the wrapper fetched it, remove "
                f"{os.path.dirname(PLUGIN)} and rerun to fetch it again), or Claude Code is too old to load plugins"
            )
        if "memory_paths" in init:
            raise RalphError(
                "Claude Code ignored the settings ralph launches agents with (auto memory is still on), "
                "so agents would not run at project scope; check that `claude --version` is up to date"
            )

    def interactive(self, prompt: str) -> int:
        """Opens an interactive session on the runner's terminal, starting from prompt. Returns its exit status.

        Claude Code takes an interactive session's first prompt as an argument; stdin is the terminal.
        """
        try:
            return subprocess.run(
                self._command([], [prompt]), cwd=self.directory, env=environment(os.environ)
            ).returncode
        except OSError as e:
            raise RalphError(f"could not start Claude Code: {e}") from e

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
                self._command(HEADLESS),
                cwd=self.directory,
                env=environment(os.environ),
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
