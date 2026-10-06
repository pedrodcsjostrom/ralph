# Agents run at project scope only

A headless agent normally inherits the runner's personal settings, instructions, memory and installed skills, which means the same spec runs under different instructions on different machines without anyone seeing the difference.
Ralph launches its agents with those user-level sources switched off, so an agent sees only what the project has checked in, the bundled skills and the project rules; authentication still comes from the runner's login.
This deliberately gives up the convenience of a maintainer's own memory reaching the agents: anything an unattended agent needs to know has to be written into the project, where it is reviewed and versioned.

## Consequences

Every agent, headless or interactive, is launched with `--setting-sources project`, `--strict-mcp-config` and settings that switch auto memory off and exclude the instruction files of every directory above the project (Claude Code counts `~/AGENTS.md` and `~/CLAUDE.md` as project memory).
At start, ralph launches a free `/context` session with the same flags and stops unless it resolves every bundled skill and applied those settings.

Checked against Claude Code 2.1.289, every user-level source of settings, instructions, memory, skills, agents, commands, plugins and MCP servers is excluded.
What no flag excludes, and so can still differ between runners:

- Per-user state in `~/.claude.json`: workspace trust (an interactive session in a project the runner has never trusted first asks to trust it), approvals of the project's `.mcp.json` servers, approvals of external `@imports` in its instruction files, and legacy per-project allowed tools.
- The runner's environment variables, such as `ANTHROPIC_MODEL` or proxy settings.
  Ralph only drops the variables of a Claude Code session it is itself started from.
- Managed settings and instructions set by an organisation's policy, which are excluded by design.
- The installed Claude Code version, which decides the built-in skills and agents.
  Ralph does not pin it.
- Interactive sessions keep their transcripts under `~/.claude/projects`; headless iterations do not.
