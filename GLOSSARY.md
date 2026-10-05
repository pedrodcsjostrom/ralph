# Ralph

Ralph implements a spec unattended, one ticket at a time, on a single branch that a human then reviews.
This glossary fixes the words the tool, its prompts and its documentation use.

## Language

### The work

**Spec**:
The parent issue that describes a piece of work to be built.
_Avoid_: PRD, epic, story

**Ticket**:
A sub-issue of a spec, sized so one agent can finish it in a single fresh context window.
_Avoid_: Task, sub-task, slice

**Fix ticket**:
A ticket created from a review finding rather than from the original split of the spec.
_Avoid_: Follow-up, finding ticket

**Frontier**:
The tickets of a spec that are open, marked ready for an agent, and have no open blocker.
_Avoid_: Queue, backlog, ready list

### The run

**Run**:
One invocation of the loop against one spec, from start until it stops.
_Avoid_: Session, job

**Iteration**:
One agent working in a fresh context window, either implementing one ticket or performing one review.
_Avoid_: Step, turn, attempt

**Attempt**:
One iteration spent on a particular ticket; a ticket may take more than one.
_Avoid_: Retry, try

**Review round**:
One review of the work together with the fix tickets it produces.
_Avoid_: Review pass, review cycle

**Fixed point**:
The commit a review compares the current work against.
_Avoid_: Base, baseline

**Run base**:
The commit a run starts from: the merge base of the integration branch with the main branch, unless configured.
It is the first review round's fixed point.
_Avoid_: Base, baseline, starting commit

**Integration branch**:
The single branch on which every commit of a spec lands.
_Avoid_: Feature branch, spec branch

**Pull request draft**:
The description of a spec's work on its integration branch, assembled from what the loop recorded in every run of the spec on that branch, that a human uses to open the pull request.
It ends with how the latest run ended.
_Avoid_: Summary, report

### The project

**Project**:
A repository that has been set up to run ralph.
_Avoid_: Consumer, host repo

**Project rules**:
Text a project supplies that is added to ralph's own instructions for every iteration in that project.
_Avoid_: Overlay, overrides, custom prompt

**Pin**:
The ralph version a project runs.
_Avoid_: Lock, version file

**Wrapper**:
The small script a project commits that obtains the pinned ralph and runs it.
_Avoid_: Shim, launcher, bootstrap

**Bundled skill**:
A copy of a skill that ships inside ralph so every runner uses the same one.
_Avoid_: Vendored skill, forked skill

### The people

**Runner**:
The person, or machine, that starts a run in a project.
_Avoid_: User, operator

**Maintainer**:
The person who changes ralph itself and releases new versions.
_Avoid_: Owner, author
