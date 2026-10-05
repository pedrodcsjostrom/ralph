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
    path = "ticket-%d.txt" % ticket
    with open(path, "a") as f:
        f.write("work on ticket %d\n" % ticket)
    git("add", path)
    git("commit", "-q", "-m", "Implement ticket (#%d)" % ticket)


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


BEHAVIOURS = {
    "complete": complete,
    "blocked": blocked,
    "no-commit": no_commit,
    "no-promise": no_promise,
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
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on ticket #%d." % ticket}]}})
    emit(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "make test"}}]},
        }
    )
    final = "Fake agent finished ticket #%d." % ticket
    if promise:
        final += " <promise>%s</promise>" % promise
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
            sys.stderr.write("fake claude: unexpected call: %s\n" % " ".join(args))
            sys.exit(2)
    except SystemExit as exit:
        call["status"] = exit.code
        raise
    finally:
        record(call)


if __name__ == "__main__":
    main(sys.argv[1:])
