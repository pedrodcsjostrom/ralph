# ralph

A deterministic loop that implements a spec one ticket at a time with headless Claude Code agents, reviews the result, and turns the review's findings into more tickets until a review is clean.

Ralph is under construction.
The vocabulary is in [GLOSSARY.md](./GLOSSARY.md) and the standing decisions are in [docs/adr](./docs/adr).

## Running it in a project

Ralph needs Python 3.9 or newer, git, the GitHub CLI (`gh`) and Claude Code (`claude`), and nothing else installed.
A project commits a small wrapper, `./ralph`, that fetches the version of ralph the project is pinned to and runs it:

```sh
./ralph split <spec issue number>   # split the spec into tickets, interactively
./ralph run <spec issue number>     # implement them unattended
./ralph help                        # every command and configuration key
```

## Setting a project up

Set-up is a maintainer command, run from a clone of ralph checked out at a release tag that is pushed to the public repository; that tag becomes the project's pin.
Link the clone's entry point onto your PATH once, so `ralph` works from any directory:

```sh
ln -s /path/to/ralph/bin/ralph ~/.local/bin/ralph
```

Then, from anywhere inside the project:

```sh
ralph setup
```

It writes the wrapper, the pin, the configuration, empty project rules, an ignore rule for run logs, the issue-tracker instructions the bundled skills read and a short section in the project's `CLAUDE.md` (or `AGENTS.md` when only that exists), and creates the `ready-for-agent` label on the project's GitHub repository.
Running it again is safe: it repairs what is missing and refreshes what is ralph's, and never touches the pin, the configuration or the project rules once they exist.
Review and commit the result.

## Developing

The suite uses the standard library test runner only:

```sh
python3 -m unittest
```
