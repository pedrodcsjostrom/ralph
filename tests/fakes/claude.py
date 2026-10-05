"""A fake Claude Code CLI: an agent that does one scripted thing per iteration.

The harness installs this file as `claude` first on the path of the run under
test. Its state lives in `$RALPH_FAKE/agent.json`:

    {"logged_in": true, "behaviours": {"3": ["blocked", "complete"]}}

The command line is parsed as the real CLI parses it (see parse): unknown
options are rejected, and an option taking several values swallows the
arguments after it up to the next option or `--`.

A headless run (`--print`) reads its prompt from stdin, finds the ticket in the
run context, and acts on the next behaviour queued for that ticket. The last
behaviour in a queue repeats; a ticket with no queue gets "complete". Every
invocation, with its arguments and prompt, is appended to
`$RALPH_FAKE/calls.jsonl`.

To add a behaviour, add a function to BEHAVIOURS. It receives the ticket number
and returns the promise to end the final message with, or None for no promise.

"pause" (seconds, default 0) is how long a headless run stays silent after
announcing its tool call, as a real agent does while a long command runs.

An interactive session (no `--print`) takes its prompt as the last argument,
acts on the ticket's next behaviour in the same way, and records the call with
"interactive": true. It prints a line of prose instead of events.

A headless `/context` prompt, given as an argument, is the start-up check: it
emits the init event a real CLI would for the plugins given with --plugin-dir,
and makes no change. With "ignores_settings": true in the state, the init event
reports auto memory on whatever --settings says, as a CLI that silently drops
settings it cannot validate does.

A review (a prompt with a "- Findings file:" line instead of a ticket) acts on
the entry for its round in "reviews":

    {"reviews": {"1": {"findings": "[...]", "also": "dirty"}}}

"findings" is the text written to the findings file, verbatim, or null to write
no file at all; a round with no entry writes "[]". "also" is an optional
misbehaviour from REVIEW_MISBEHAVIOURS.
"""

import json
import os
import re
import signal
import subprocess
import sys
import time

FAKE = os.environ["RALPH_FAKE"]
STATE = os.path.join(FAKE, "agent.json")


def load():
    with open(STATE) as f:
        return json.load(f)


def save(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE)


def record(call):
    with open(os.path.join(FAKE, "calls.jsonl"), "a") as f:
        f.write(json.dumps(call) + "\n")


def git(*args):
    subprocess.run(("git",) + args, check=True, stdout=subprocess.DEVNULL)


def commit(ticket):
    path = f"ticket-{ticket}.txt"
    with open(path, "a") as f:
        f.write(f"work on ticket {ticket}\n")
    git("add", path)
    git("commit", "-q", "-m", f"Implement ticket (#{ticket})")


def complete(ticket):
    commit(ticket)
    return "TICKET COMPLETE"


def blocked(ticket):
    return "TICKET BLOCKED"


def no_commit(ticket):
    """Claims completion without committing anything."""
    return "TICKET COMPLETE"


def no_promise(ticket):
    """Commits but never says it is done."""
    commit(ticket)
    return None


def dirty(ticket):
    """Leaves a change uncommitted and says it is blocked."""
    with open(f"ticket-{ticket}.txt", "a") as f:
        f.write("work in progress\n")
    return "TICKET BLOCKED"


def complete_dirty(ticket):
    """Commits and claims completion, but leaves a change uncommitted too."""
    commit(ticket)
    with open(f"ticket-{ticket}.txt", "a") as f:
        f.write("work in progress\n")
    return "TICKET COMPLETE"


def switch_branch(ticket):
    """Commits its work on a new branch, `elsewhere`, and leaves the checkout there."""
    git("switch", "-q", "-c", "elsewhere")
    return complete(ticket)


def detach(ticket):
    """Commits its work, then detaches HEAD."""
    promise = complete(ticket)
    git("switch", "-q", "--detach")
    return promise


def crash(ticket):
    """Claude Code itself fails, exiting with status 3."""
    sys.stderr.write("fake claude: crashed\n")
    sys.exit(3)


def interrupt(ticket):
    """Commits, then interrupts ralph as Ctrl-C on the terminal would (ralph is this process's parent)."""
    commit(ticket)
    os.kill(os.getppid(), signal.SIGINT)
    return "TICKET COMPLETE"


BEHAVIOURS = {
    "crash": crash,
    "complete": complete,
    "blocked": blocked,
    "no-commit": no_commit,
    "no-promise": no_promise,
    "dirty": dirty,
    "complete-dirty": complete_dirty,
    "switch-branch": switch_branch,
    "detach": detach,
    "interrupt": interrupt,
}


def review_dirty():
    with open("review-notes.txt", "w") as f:
        f.write("notes the review left behind\n")


def review_commit():
    with open("review-fix.txt", "w") as f:
        f.write("a fix the review should not have made\n")
    git("add", "review-fix.txt")
    git("commit", "-q", "-m", "Fix what the review found")


def review_switch_branch():
    git("switch", "-q", "-c", "elsewhere")


REVIEW_MISBEHAVIOURS = {
    "dirty": review_dirty,
    "commit": review_commit,
    "switch-branch": review_switch_branch,
}


def review(state, prompt, findings_file, call):
    round_ = int(re.search(r"^- Review round: (\d+)$", prompt, re.M).group(1))
    plan = state.get("reviews", {}).get(str(round_), {"findings": "[]"})
    call.update(review=round_, findings_file=findings_file)
    if plan.get("findings") is not None:
        with open(findings_file, "w") as f:
            f.write(plan["findings"])
    if plan.get("also"):
        REVIEW_MISBEHAVIOURS[plan["also"]]()

    print("not json, as a real run prints before its first event")
    emit({"type": "system", "subtype": "init", "session_id": "fake"})
    final = f"Fake review round {round_} done."
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
    emit({"type": "result", "subtype": "success", "result": final})


def next_behaviour(state, ticket):
    queue = state.setdefault("behaviours", {}).get(str(ticket)) or ["complete"]
    if len(queue) > 1:
        state["behaviours"][str(ticket)] = queue[1:]
        save(state)
    return queue[0]


# The options the fake understands, by how many values they take.
FLAGS = {"--print", "-p", "--verbose", "--strict-mcp-config", "--no-session-persistence"}
SINGLE = {
    "--output-format",
    "--settings",
    "--permission-mode",
    "--plugin-dir",
    "--setting-sources",
    "--model",
    "--append-system-prompt",
}
VARIADIC = {"--allowedTools", "--disallowedTools", "--add-dir", "--tools"}


def parse(args):
    """The options and positional arguments of a command line, as the real CLI reads them.

    Single-value options may repeat (each value is kept); an option taking several values
    takes every following argument up to the next option or `--`.
    """
    options, positionals = {}, []
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            positionals += args[i:]
            break
        if not arg.startswith("-"):
            positionals.append(arg)
        elif arg in FLAGS:
            options[arg] = True
        elif arg in SINGLE:
            if i >= len(args):
                fail(f"error: option '{arg}' argument missing")
            options.setdefault(arg, []).append(args[i])
            i += 1
        elif arg in VARIADIC:
            values = options.setdefault(arg, [])
            while i < len(args) and not args[i].startswith("-"):
                values.append(args[i])
                i += 1
        else:
            fail(f"error: unknown option '{arg}'")
    return options, positionals


def fail(message):
    sys.stderr.write(message + "\n")
    sys.exit(1)


def context(state, options, call):
    """The start-up check: the init event for the plugins and settings given, as `/context` makes no model call."""
    call["context"] = True
    skills, plugins = ["code-review", "simplify"], []
    for directory in options.get("--plugin-dir", []):
        # The real CLI silently ignores a plugin directory it cannot load.
        try:
            with open(os.path.join(directory, ".claude-plugin", "plugin.json")) as f:
                name = json.load(f)["name"]
        except (OSError, ValueError, KeyError):
            continue
        plugins.append({"name": name, "path": directory, "source": f"{name}@inline"})
        found = os.path.join(directory, "skills")
        for skill in sorted(os.listdir(found)) if os.path.isdir(found) else []:
            if os.path.isfile(os.path.join(found, skill, "SKILL.md")):
                skills.append(f"{name}:{skill}")
    init = {"type": "system", "subtype": "init", "session_id": "fake", "skills": skills, "plugins": plugins}
    settings = {}
    for text in options.get("--settings", []):
        try:
            settings.update(json.loads(text))
        except ValueError:
            pass
    if state.get("ignores_settings") or settings.get("autoMemoryEnabled") is not False:
        init["memory_paths"] = {"auto": os.path.join(os.environ["HOME"], ".claude", "projects", "memory")}
    emit(init)
    emit({"type": "result", "subtype": "success", "result": "## Context Usage", "total_cost_usd": 0})


def emit(event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def headless(state, options, positionals, call):
    if options.get("--output-format") != ["stream-json"] or "--verbose" not in options:
        sys.stderr.write("fake claude: expected --output-format stream-json --verbose\n")
        sys.exit(2)
    if positionals == ["/context"]:
        context(state, options, call)
        return
    if positionals:
        sys.stderr.write(f"fake claude: expected the prompt on stdin, not as arguments {positionals}\n")
        sys.exit(2)
    prompt = sys.stdin.read()
    call["prompt"] = prompt
    findings = re.search(r"^- Findings file: (.+)$", prompt, re.M)
    if findings:
        review(state, prompt, findings.group(1), call)
        return
    match = re.search(r"^- Ticket: #(\d+)$", prompt, re.M)
    if not match:
        sys.stderr.write("fake claude: no ticket in the prompt\n")
        sys.exit(2)
    ticket = int(match.group(1))
    behaviour = next_behaviour(state, ticket)
    call.update(ticket=ticket, behaviour=behaviour)
    promise = BEHAVIOURS[behaviour](ticket)

    # A real run prints a line that is not an event before the first event.
    print("not json, as a real run prints before its first event")
    emit({"type": "system", "subtype": "init", "session_id": "fake"})
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Working on ticket #{ticket}."}]}})
    emit(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_fake",
                        "name": "Bash",
                        "input": {"command": "make test", "description": "Run the tests"},
                    }
                ]
            },
        }
    )
    # A long tool call: the agent emits nothing while it lasts.
    time.sleep(state.get("pause", 0))
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_fake"}]}})
    final = f"Fake agent finished ticket #{ticket}."
    if promise:
        final += f" <promise>{promise}</promise>"
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
    emit({"type": "result", "subtype": "success", "result": final})


def interactive(state, positionals, call):
    if len(positionals) != 1:
        sys.stderr.write(f"fake claude: expected the prompt as the only argument, got {positionals}\n")
        sys.exit(2)
    prompt = positionals[0]
    call.update(interactive=True, prompt=prompt)
    match = re.search(r"^- Ticket: #(\d+)$", prompt, re.M)
    if not match:
        sys.stderr.write("fake claude: no ticket in the prompt\n")
        sys.exit(2)
    ticket = int(match.group(1))
    behaviour = next_behaviour(state, ticket)
    call.update(ticket=ticket, behaviour=behaviour)
    BEHAVIOURS[behaviour](ticket)
    print(f"Fake interactive session on ticket #{ticket} ended.")


def auth_status(state, args, call):
    logged_in = state.get("logged_in", True)
    print(json.dumps({"loggedIn": logged_in}))
    if not logged_in:
        sys.exit(1)


def main(args):
    # Interrupted, it stops quietly, as the real CLI does.
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    # What the agent inherits of a Claude Code session ralph itself runs in.
    inherited = {k: v for k, v in os.environ.items() if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_")}
    call = {"tool": "claude", "args": args, "env": inherited}
    try:
        state = load()
        if args[:2] == ["auth", "status"]:
            auth_status(state, args, call)
            return
        options, positionals = parse(args)
        call["options"] = options
        if "--print" in options or "-p" in options:
            headless(state, options, positionals, call)
        else:
            interactive(state, positionals, call)
    except SystemExit as exit:
        call["status"] = exit.code
        raise
    finally:
        record(call)


if __name__ == "__main__":
    main(sys.argv[1:])
