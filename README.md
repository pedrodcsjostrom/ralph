# ralph

Ralph implements a spec unattended, one ticket at a time, with headless Claude Code agents.
Every commit lands on one integration branch.
When the tickets are done, an agent reviews the work, the review's findings become fix tickets, and ralph implements those too, until a review round is clean.
A human then reviews the branch and opens the pull request from the pull request draft ralph leaves.

The vocabulary used here and in ralph's prompts is in [GLOSSARY.md](./GLOSSARY.md), and the standing decisions are in [docs/adr](./docs/adr).

## What you need

- Linux or macOS.
  Windows works through WSL only.
- Python 3.9 or newer, git, the GitHub CLI (`gh`, logged in) and Claude Code (`claude`, logged in).
  Nothing else is installed.
- A project on GitHub.
  Specs and tickets are GitHub issues: a ticket is a sub-issue of its spec, labelled `ready-for-agent`, with its blockers recorded as issue dependencies.

## Adopting ralph in a project

A maintainer sets a project up once, from a clone of ralph.
Link the clone's entry point onto your PATH, so `ralph` works from any directory:

```sh
ln -s /path/to/ralph-clone/bin/ralph ~/.local/bin/ralph
```

Check the clone out at a release tag that is pushed to the public repository, then run, from anywhere inside the project:

```sh
ralph setup
```

The tag becomes the project's pin.
To pin a version without checking it out, name it: `ralph setup --pin v0.1.0`.
That works even for a tag not yet released, so a project can be set up ahead of its release; set-up warns that the wrapper cannot run until the tag is pushed to the public repository.

Set-up writes:

- the wrapper, `./ralph` at the project root;
- the pin, `.ralph/pin`;
- the configuration, `.ralph/config`, with every key commented out at its default;
- empty project rules, `.ralph/rules/implement.md` and `.ralph/rules/review.md`;
- `docs/agents/issue-tracker.md`, the issue-tracker instructions the bundled skills read;
- a short section about ralph in the project's `CLAUDE.md`, or in `AGENTS.md` when only that exists.

It also creates the `ready-for-agent` label on the project's GitHub repository when it is missing.
Nothing is committed: review the changes and commit them.
Running set-up again is safe.
It repairs what is missing and refreshes what is ralph's, and never touches the pin, the configuration or the project rules once they exist.

## Running ralph

A runner uses the wrapper the project has committed.
It fetches the pinned version of ralph into a per-user cache the first time, then runs it.
Every command acts on the wrapper's project, wherever it is run from.

```sh
./ralph split <spec>     # split the spec into tickets, interactively
./ralph watch <spec>     # watch one iteration before leaving a run unattended
./ralph run <spec>       # implement and review the spec unattended
./ralph publish          # push the integration branch and open the pull request
./ralph upgrade          # move the pin to the newest release
./ralph help             # every command, configuration key and environment variable
```

- **split**: opens an interactive Claude Code session that agrees a breakdown of the spec with you, then opens its tickets.
  Run it before a spec's first run.
- **watch**: opens an interactive session on the ticket a run would implement next, on the same integration branch and with the same prompt.
  It closes nothing; close the ticket yourself when its commits are good.
- **run**: implements the frontier one ticket at a time, each iteration in a fresh context window, then runs review rounds until one is clean.
  A ticket gets a limited number of attempts, and a run a limited number of iterations and review rounds.
  When a budget is spent or nothing more can be implemented it stops and says why; rerun to carry on.
  Nothing is pushed.
  Every run ends by naming its pull request draft, which covers every run of the spec on its integration branch.
- **publish**: pushes the latest run's integration branch to `origin` and opens a pull request against the main branch, with the pull request draft as its body.
  It refuses a run that did not end cleanly unless you add `--force`.
- **upgrade**: moves the pin to the newest release, or to a named one with `./ralph upgrade <version>`.
  Commit the changed pin to upgrade every runner.

## Configuring a project

`.ralph/config` is checked in and holds one `key = value` per line.
The keys are `verify` (a shell command that must pass before a ticket is closed), `main_branch`, `run_base`, `max_attempts`, `max_review_rounds`, `max_iterations` and `agent_flags`.
`RALPH_<KEY>` in the environment overrides a key for one run, as in `RALPH_MAX_ATTEMPTS=1 ./ralph run 12`.
`./ralph help` documents every key and its default.

The project rules add to ralph's own instructions and never replace them.
Text in `.ralph/rules/implement.md` goes into every implementing iteration, and text in `.ralph/rules/review.md` into every review.

Agents run at project scope with ralph's bundled skills loaded for their session only.
They see what the project has checked in, the bundled skills and the project rules, but none of the runner's personal Claude Code settings, instructions, memory, skills or MCP servers.
The limits of that isolation are in [ADR 0002](./docs/adr/0002-agents-run-at-project-scope-only.md).

## Limits

- Linux and macOS only; Windows through WSL only.
- GitHub is the only tracker and Claude Code the only agent.
- One ticket at a time, in one checkout: a run works in the checkout it is started in, so do not start two runs in the same checkout.

## Maintaining ralph

Ralph is stdlib-only Python, run straight from a checkout: `bin/ralph` is the entry point, the code is in `src/ralph/`, the wrapper's source is `wrapper/ralph` and the bundled skills are in `plugin/`.

```sh
python3 -m unittest                              # the test suite
uvx ruff check . && uvx ruff format --check .    # lint, as CI runs it
```

### Ralph runs on itself

Ralph's own repository is a project, set up with ralph, and the place the tool is proven.
Its `.ralph/config` sets `verify = python3 -m unittest`.
Its pin is `v0.1.0`, the first release, which is not published yet: `./ralph` in this repository fails until the `v0.1.0` tag is pushed to the public repository.

### Bundled skills

The bundled skills in `plugin/` are generated copies of the maintainer's own skills, and are never edited by hand.
To change one, change the original skill, then regenerate them all:

```sh
ralph sync-skills    # reads ~/.claude/skills by default
```

It repoints references between bundled skills to their `ralph:` names and reports references to skills that are not bundled.
Review the result as a diff and commit it.

### Releases

A release is a version tag, such as `v0.2.0`, pushed to the public repository; the wrapper fetches the tag a project's pin names.
Tag a commit on main where the suite passes, then push the tag:

```sh
git tag v0.2.0 && git push origin v0.2.0
```

Projects move to it with `./ralph upgrade`, ralph's own repository included.
A pushed tag must never move, because projects already pinned to it would silently run different code.
