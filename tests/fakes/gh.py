"""A fake GitHub CLI: an in-memory tracker that records every call.

The harness installs this file as `gh` first on the path of the run under test.
Its state lives in `$RALPH_FAKE/tracker.json` (see `tests/harness.py` for the
shape; "delay" makes every call take that many seconds) and every invocation
is appended to `$RALPH_FAKE/calls.jsonl`.

Only the calls ralph is known to make are understood. Anything else exits
non-zero with "fake gh: unexpected call", so a new use of `gh` in ralph fails
loudly until this fake learns it.

To teach it a new call, add a handler to HANDLERS keyed by the first two
arguments (or the first one, for `api`). A handler that changes the tracker
saves the state and returns {"mutation": <name>, ...}; that is merged into the
call's record, which is how tests observe mutations.
"""

import json
import os
import re
import subprocess
import sys
import time

FAKE = os.environ["RALPH_FAKE"]
STATE = os.path.join(FAKE, "tracker.json")


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


def fail(message, status=1):
    sys.stderr.write(message + "\n")
    sys.exit(status)


def unexpected(args):
    fail("fake gh: unexpected call: " + " ".join(args), 2)


# The `gh api` options ralph uses that take a value.
API_VALUE_OPTIONS = {"--method", "-X", "--input", "--field", "-F", "--raw-field", "-f"}


def api_path(args):
    """The endpoint of a `gh api` call: its one positional argument."""
    positional = [
        a for i, a in enumerate(args) if i > 0 and not a.startswith("-") and args[i - 1] not in API_VALUE_OPTIONS
    ]
    return positional[0] if positional else ""


def option(args, name):
    """The value following `name` in args, or None."""
    for i, arg in enumerate(args[:-1]):
        if arg == name:
            return args[i + 1]
    return None


def issue(state, number):
    found = state["issues"].get(str(number))
    if found is None:
        fail(f"GraphQL: Could not resolve to an issue or pull request with the number of {number}.")
    return found


def url(state, number):
    return "https://github.com/{}/issues/{}".format(state["repo"], number)


def open_blockers(state, ticket):
    return sum(
        1 for n in ticket.get("blocked_by", []) if state["issues"].get(str(n), {}).get("state", "open") == "open"
    )


def auth_status(state, args):
    if not state.get("logged_in", True):
        fail("You are not logged into any GitHub hosts. To log in, run: gh auth login")
    print("github.com\n  Logged in to github.com account fake")


def repo_view(state, args):
    fields = (option(args, "--json") or "").split(",")
    data = {"nameWithOwner": state["repo"], "name": state["repo"].split("/")[1]}
    print(json.dumps({k: data[k] for k in fields if k in data}))


def issue_view(state, args):
    number = int(args[2])
    found = issue(state, number)
    data = {
        "number": number,
        "title": found["title"],
        "url": url(state, number),
        "state": found.get("state", "open").upper(),
        "body": found.get("body", ""),
        "comments": [{"author": {"login": "someone"}, "body": c} for c in found.get("comments", [])],
        "labels": [{"name": n} for n in found.get("labels", [])],
    }
    fields = (option(args, "--json") or "").split(",")
    print(json.dumps({k: data[k] for k in fields if k in data}))


def issue_close(state, args):
    number = int(args[2])
    issue(state, number)["state"] = "closed"
    comment = option(args, "--comment") or option(args, "-c")
    if comment is not None:
        issue(state, number).setdefault("comments", []).append(comment)
    save(state)
    return {"mutation": "close", "ticket": number, "comment": comment}


def issue_comment(state, args):
    number = int(args[2])
    body = option(args, "--body") or option(args, "-b")
    issue(state, number).setdefault("comments", []).append(body)
    save(state)
    return {"mutation": "comment", "ticket": number, "body": body}


def pr_create(state, args):
    """`gh pr create --repo R --base B --head H --title T --body-file -`. Like gh, it wants the head pushed first."""
    head, base = option(args, "--head"), option(args, "--base")
    if option(args, "--repo") != state["repo"] or None in (head, base) or option(args, "--body-file") != "-":
        unexpected(args)
    pushed = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", "origin", head], stdout=subprocess.DEVNULL)
    if pushed.returncode != 0:
        fail("aborted: you must first push the current branch to a remote, or use the --head flag")
    pulls = state.setdefault("pull_requests", [])
    number = max([int(n) for n in state["issues"]] + [p["number"] for p in pulls]) + 1
    pull = {"number": number, "base": base, "head": head, "title": option(args, "--title"), "body": sys.stdin.read()}
    pulls.append(pull)
    save(state)
    print("https://github.com/{}/pull/{}".format(state["repo"], number))
    return {"mutation": "pull request", "ticket": number, "pull": pull}


def create_issue(state, args):
    """`gh api repos/<repo>/issues --method POST --input -`: the new issue's fields come in on stdin."""
    fields = json.load(sys.stdin)
    number = max(int(n) for n in state["issues"]) + 1
    state["issues"][str(number)] = {
        "title": fields["title"],
        "state": "open",
        "labels": list(fields.get("labels", [])),
        "blocked_by": [],
        "body": fields.get("body", ""),
        "comments": [],
    }
    save(state)
    print(json.dumps({"number": number, "id": number * 1000, "html_url": url(state, number)}))
    return {"mutation": "create", "ticket": number, "fields": fields}


def add_sub_issue(state, args, spec):
    """`gh api repos/<repo>/issues/<spec>/sub_issues --method POST -F sub_issue_id=<id>`."""
    field = option(args, "-F") or option(args, "--field") or ""
    if not field.startswith("sub_issue_id="):
        unexpected(args)
    number = int(field.split("=", 1)[1]) // 1000
    issue(state, number)
    issue(state, spec)["sub_issues"].append(number)
    save(state)
    print(json.dumps({"number": spec}))
    return {"mutation": "link", "ticket": number, "spec": spec}


def api(state, args):
    path = api_path(args)
    method = option(args, "--method") or option(args, "-X")
    if method == "POST":
        if path == "repos/{}/issues".format(state["repo"]) and option(args, "--input") == "-":
            return create_issue(state, args)
        match = re.match(r"repos/([^/]+/[^/]+)/issues/(\d+)/sub_issues$", path)
        if match and match.group(1) == state["repo"]:
            return add_sub_issue(state, args, int(match.group(2)))
        unexpected(args)
    match = re.match(r"repos/([^/]+/[^/]+)/issues/(\d+)/sub_issues(\?.*)?$", path)
    if match and match.group(1) == state["repo"] and method is None:
        spec = issue(state, int(match.group(2)))
        tickets = []
        for n in spec.get("sub_issues", []):
            t = issue(state, n)
            tickets.append(
                {
                    "number": n,
                    "id": n * 1000,
                    "title": t["title"],
                    "state": t.get("state", "open"),
                    "labels": [{"name": name} for name in t.get("labels", [])],
                    "issue_dependencies_summary": {
                        "blocked_by": open_blockers(state, t),
                        "total_blocked_by": len(t.get("blocked_by", [])),
                    },
                }
            )
        # `gh api --paginate` prints each page as its own JSON document, back
        # to back. Two pages exercise ralph's handling of that.
        half = len(tickets) // 2
        sys.stdout.write(json.dumps(tickets[:half]) + json.dumps(tickets[half:]) + "\n")
        return
    unexpected(args)


HANDLERS = {
    ("auth", "status"): auth_status,
    ("repo", "view"): repo_view,
    ("issue", "view"): issue_view,
    ("issue", "close"): issue_close,
    ("issue", "comment"): issue_comment,
    ("pr", "create"): pr_create,
    ("api",): api,
}


def main(args):
    call = {"tool": "gh", "args": args}
    try:
        handler = HANDLERS.get(tuple(args[:2])) or HANDLERS.get(tuple(args[:1]))
        if handler is None:
            unexpected(args)
        state = load()
        time.sleep(state.get("delay", 0))
        call.update(handler(state, args) or {})
    except SystemExit as exit:
        call["status"] = exit.code
        raise
    finally:
        record(call)


if __name__ == "__main__":
    main(sys.argv[1:])
