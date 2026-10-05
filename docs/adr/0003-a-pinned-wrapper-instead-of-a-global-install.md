# A pinned wrapper instead of a global install

Ralph's prompts and bundled skills change how a run behaves, and they are still being tuned, so a project must not change behaviour because ralph changed for some other project.
Each project commits a small wrapper and a pin; the wrapper fetches that version of ralph into a per-user cache on first use and runs it, so cloning the project is enough to run it and every runner of a project uses the same version.
The ralph repository is public so that fetch needs no credentials.

## Considered Options

- A global install per machine: simplest, but two runners can run the same spec with different loops, and there is an install step to discover.
- Vendoring ralph into each project: pinned by git, but the engine and skills are duplicated in every repository and show up in its reviews.
