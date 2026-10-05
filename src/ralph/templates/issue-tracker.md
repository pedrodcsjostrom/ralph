<!-- Written by `ralph setup`, which refreshes it. Delete this line to keep your own version instead. -->
# Issue tracker: GitHub

Issues and specs for this repository live as GitHub issues.
Use the `gh` CLI for every operation; inside the clone it finds the repository from `git remote -v`.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body-file -`, with the body on stdin.
- **Read an issue**: `gh issue view <number> --comments`.
- **List issues**: `gh issue list --state open --json number,title,labels`, with `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`.
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- **Close**: `gh issue close <number> --comment "..."`.

## Specs and tickets

A spec is an issue; its tickets are its GitHub sub-issues, and a ticket's blockers are native issue dependencies.

- **Add a ticket to its spec**: `gh api repos/<owner>/<repo>/issues/<spec>/sub_issues --method POST -F sub_issue_id=<ticket id>`.
- **Record a blocker**: `gh api repos/<owner>/<repo>/issues/<ticket>/dependencies/blocked_by --method POST -F issue_id=<blocker id>`.
- An id is the issue's database id, `gh api repos/<owner>/<repo>/issues/<number> --jq .id`, not its number.

## Triage labels

`ready-for-agent` is the only triage label: a ticket carrying it is fully specified, and ralph implements it once its blockers are closed.
Apply it to every ticket you open for an agent.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
