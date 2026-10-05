# Bundled skills are generated copies in a session-only plugin

Ralph's behaviour comes mostly from the skills its agents invoke, and those skills are the maintainer's personal ones, which no other runner has.
Ralph therefore ships its own copies as a Claude Code plugin that is loaded for each agent session only and invoked under the `ralph:` namespace, so nothing is installed on the runner's machine and nothing installed there can shadow them.
The copies are generated from the maintainer's skills by a sync command and are never edited by hand, so refreshing them stays a plain overwrite; anything that must differ for unattended use belongs in ralph's own prompts.

## Considered Options

- Requiring each runner to have the skills installed: the loop would silently differ per machine.
- Installing the copies into the runner's user-level skills: it overwrites, or is overwritten by, the runner's own skills of the same name.
- Inlining skill text into the prompts: every cross-reference and supporting file must be flattened by hand on each refresh.
- Editable forks of the skills: every refresh becomes a merge.
