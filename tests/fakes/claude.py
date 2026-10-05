"""A fake Claude Code CLI: an agent that does one scripted thing per iteration.

The harness installs this file as `claude` first on the path of the run under
test. Its state lives in `$RALPH_FAKE/agent.json`:

    {"logged_in": true, "behaviours": {"3": ["blocked", "complete"]}}

A headless run (`--print`) reads its prompt from stdin, finds the ticket in the
run context, and acts on the next behaviour queued for that ticket. The last
behaviour in a queue repeats; a ticket with no queue gets "complete". Every
invocation, with its arguments and prompt, is appended to
`$RALPH_FAKE/calls.jsonl`.

To add a behaviour, add a function to BEHAVIOURS. It receives the ticket number
and returns the promise to end the final message with, or None for no promise.
"""

import json
import os
import re
import subprocess
import sys

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


BEHAVIOURS = {
    "complete": complete,
    "blocked": blocked,
    "no-commit": no_commit,
    "no-promise": no_promise,
    "dirty": dirty,
    "complete-dirty": complete_dirty,
    "switch-branch": switch_branch,
    "detach": detach,
}


def next_behaviour(state, ticket):
    queue = state.setdefault("behaviours", {}).get(str(ticket)) or ["complete"]
    if len(queue) > 1:
        state["behaviours"][str(ticket)] = queue[1:]
        save(state)
    return queue[0]


def emit(event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def headless(state, args, call):
    if "--output-format" not in args or args[args.index("--output-format") + 1] != "stream-json":
        sys.stderr.write("fake claude: expected --output-format stream-json\n")
        sys.exit(2)
    prompt = sys.stdin.read()
    call["prompt"] = prompt
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
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "make test"}}]},
        }
    )
    final = f"Fake agent finished ticket #{ticket}."
    if promise:
        final += f" <promise>{promise}</promise>"
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
    emit({"type": "result", "subtype": "success", "result": final})


def auth_status(state, args, call):
    logged_in = state.get("logged_in", True)
    print(json.dumps({"loggedIn": logged_in}))
    if not logged_in:
        sys.exit(1)


def main(args):
    call = {"tool": "claude", "args": args}
    try:
        state = load()
        if args[:2] == ["auth", "status"]:
            auth_status(state, args, call)
        elif "--print" in args or "-p" in args:
            headless(state, args, call)
        else:
            sys.stderr.write("fake claude: unexpected call: {}\n".format(" ".join(args)))
            sys.exit(2)
    except SystemExit as exit:
        call["status"] = exit.code
        raise
    finally:
        record(call)


if __name__ == "__main__":
    main(sys.argv[1:])
