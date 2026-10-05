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

"pause" (seconds, default 0) is how long a headless run stays silent after
announcing its tool call, as a real agent does while a long command runs.

An interactive session (no `--print`) takes its prompt as the last argument,
acts on the ticket's next behaviour in the same way, and records the call with
"interactive": true. It prints a line of prose instead of events.

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


def emit(event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def headless(state, args, call):
    if "--output-format" not in args or args[args.index("--output-format") + 1] != "stream-json":
        sys.stderr.write("fake claude: expected --output-format stream-json\n")
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


def interactive(state, args, call):
    if not args or args[-1].startswith("-"):
        sys.stderr.write("fake claude: expected the prompt as the last argument\n")
        sys.exit(2)
    prompt = args[-1]
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
    call = {"tool": "claude", "args": args}
    try:
        state = load()
        if args[:2] == ["auth", "status"]:
            auth_status(state, args, call)
        elif "--print" in args or "-p" in args:
            headless(state, args, call)
        else:
            interactive(state, args, call)
    except SystemExit as exit:
        call["status"] = exit.code
        raise
    finally:
        record(call)


if __name__ == "__main__":
    main(sys.argv[1:])
