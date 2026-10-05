# ralph

A deterministic loop that implements a spec one ticket at a time with headless Claude Code agents, reviews the result, and turns the review's findings into more tickets until a review is clean.

Ralph is under construction.
The vocabulary is in [GLOSSARY.md](./GLOSSARY.md) and the standing decisions are in [docs/adr](./docs/adr).

## Running from a checkout

Ralph needs Python 3.9 or newer, git, the GitHub CLI (`gh`) and Claude Code (`claude`), and nothing else installed.
From a clean checkout of a project, on its main branch or on the branch the work should land on:

```sh
/path/to/ralph/bin/ralph run <spec issue number>
```

## Developing

The suite uses the standard library test runner only:

```sh
python3 -m unittest
```
