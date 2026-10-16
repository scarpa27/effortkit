# Workflow contract of {{project}}

This instance of effortkit lives in `{{instance}}`. The kit lives in `{{kit}}`.

## Words

- **Effort**: one unit of work.
  It has one plan folder, one tree or none, one branch and one supervisor session.
- **Home supervisor**: the owner's chat at `{{instance}}`. It has no tree.
- **Kind**: the type of an effort. It selects the repository of the tree and the lane skill.
{{kinds_list}}

## The plan folder

`{{plan}}/<effort>/` holds:

| File | Writer |
|---|---|
| `effort.json` | `effort new`, once. It holds the name, kind, branch, base commit and tree. |
| `approval.json`, `closed.json`, `runs/` | the effort command only |
| `status.md` | the supervisor of the effort, and nobody else |
| `related.md` | the supervisor. One related effort per line. |
| `briefs/<UTC time>-<role>.md` | the supervisor, before `effort run` |
| `task.md`, `questions.md` | the planner, or the improver in a kit or overlay effort |
| `answers.md` | the supervisor |
| `exploration-brief.md`, `research-brief.md`, `investigation.md`, `triage.md` | explorer, researcher, debugger, improver |
| `dev-notes.md`, `test-notes.md`, `review.md` | developer, tester, reviewer |
| `decision.md` | any role, when a choice needs the owner |
| `findings/<UTC time>-<role>.md` | any role, one file per finding about the project |
| `review/` | `effort plan-review`: the review pages |
| `scratch/` | any role. Bulk logs, run logs and the gate log. Git ignores it. |

- One file has one writer.
  Two parallel stages of one role get two artifact names in their briefs, for example `review-1.md` and `review-2.md`.
- `status.md` format:
  ```
  # <effort>
  ## Stage: <stage>
  ## Ticket: <key> or none
  ## Last Activity: <what happened last>
  ## Current Wave: <n of m, and what it does>
  ## Blockers: <what stops the work, or none>
  ## Notes: <what a fresh session needs to resume>
  ```
- Stages: EXPLORING, RESEARCHING, INVESTIGATING, PLANNING, AWAITING_ANSWERS, APPROVED, IMPLEMENTING, TESTING, REVIEWING, AWAITING_DECISION, BLOCKED, COMPLETE, ABANDONED.
- The stage informs the owner. It is not a permission, and no gate reads it.

## Plan format

The planner writes `task.md` and `questions.md` in this format. The improver does too, in a kit or overlay effort.

`task.md`:
```markdown
# Task: <short description>
## Request
<faithful summary>
## Key context
<constraints, patterns, integration points>
## Waves
### Wave 1: <goal>
| Sub-task | Agent | Details | Artifact |
| --- | --- | --- | --- |
## Files to create or change
<absolute paths>
## Tests
<the tests to write or change, and the commands that run them>
## Exit criteria
<what must be true at the end, stated as properties, not as counts>
## Risks and assumptions
<material ones only>
```
`questions.md`: exactly `NO_QUESTIONS`, or one block per question in this format:
```markdown
## Q1: <the question, in one sentence>
Recommended: <your recommended answer>
Depends on: <the fact that the safe answer depends on>
Why: <short context, optional>
```
The plan-review page shows each block as a card, so keep the format exact.

## Read and write

- Every session may read every plan folder, the knowledge and the reference material.
- A session writes only in its own tree, its own plan folder, the knowledge inbox, the workflow-report inbox and `/tmp`.
  The role limits the tree further: the developer writes the whole tree, the tester only {{tester_globs}}, the other roles nothing.

## Approval

- The developer and the tester change the tree only when `approval.json` exists and its hash matches the current `task.md`.
- Only the owner approves, with `!effort approve <effort>` in the chat or in a terminal.
- An agent never runs `effort approve`, and never writes `approval.json`.
- A changed `task.md` needs a new approval.

## Duties at the end of every stage

1. Write your artifact in the plan folder.
2. Record each new finding about the project as its own file in `findings/`, and list it under `## NEW ISSUES` in your reply.
   Do not fix an unrelated problem, and do not widen the task.
3. Record each problem that the workflow caused you as a workflow report in `{{reports}}/`, and name the files under `## IMPROVEMENT` in your reply, or write `## IMPROVEMENT: none`.
4. Put a durable fact about the project into the knowledge inbox `{{knowledge_inbox}}/`.

## Workflow reports and the improvement loop

- A workflow report says what made the work slower or worse, and what would be better.
  The format is in the prompt of every role: the lines `scope`, `area` and `severity`, then `## What happened`, `## What would be better` and `## Evidence`.
- `scope: kit` is the generic machinery in `{{kit}}`. `scope: overlay` is the rules of {{project}} in `{{overlay}}` and `{{instance}}/instance.json`.
- The gates log every refusal, and the effort command logs every run. The improver reads those signals too, so a report needs no copy of a refusal: it adds what the refusal cannot say.
- `effort improve` starts an improvement round: an effort of kind `kit` or `overlay` in which the improver triages the reports and plans the fixes.
  The owner approves that plan like any other, and the developer implements it in a tree of the layer.
- `effort close` of an improvement effort files each report that `triage.md` decided into `worklog/improvements/done/` and the ledger.
- The aim is fewer reports per effort over time. `effort improve stats` shows the trend.

## Skills

- Every skill that an agent loads is a workspace copy in `{{instance}}/.kiro/skills/`.
  `effort gen` makes the copies from the kit and from `{{overlay}}/skills/`.
- No agent loads a skill from the machine, for example from `~/.kiro/skills`.
  A skill that a role needs goes into the kit (an effort of kind kit) or into the overlay (an effort of kind overlay).
- Do not edit a workspace copy. The next `effort gen` replaces it.

## Knowledge

- Topic files: `{{knowledge}}/<topic>.md`.
- During an effort, do not edit a topic file. Write one inbox file instead, and name the target topic in its first line.
- The supervisor merges the inbox into the topic files when the effort closes.

## Git

- Commit locally after each wave. The subject looks like `{{commit_help}}`. No co-author line.
- Never push, force push, `reset --hard`, `clean -f`, `branch -D` or `--no-verify`.
- A backup of the effort's own branch is allowed: `git branch <effort branch>-<suffix>`.

## Gates

The gate hook checks every write, shell, code, read, glob, grep and MCP call before it runs.

| Gate | Rule |
|---|---|
| Identity | The session runs in its effort's tree, or at the instance root. `EFFORTKIT_EFFORT` must agree with the tree. |
| Scope | A change goes only to the zones of the role (above). Only the supervisor writes `status.md` and the knowledge topic files. |
| Approval | A tree change, a git change or an unknown command of the developer or the tester needs a valid `approval.json`. Reading, the configured test commands and writing the plan folder do not. |
| Commands | No push, `reset --hard`, `clean -f`, `--no-verify`, hooksPath, `sudo`, uploads, `effort approve`, branch changes, and none of the forbidden commands of `instance.json`. A forge write (glab, gh) and an MCP write are for the supervisor only, after the owner said yes. |
| Commit message | The subject matches the rule of the repository, with no co-author line. |
| Read-only shell | The roles without a writer profile run only read commands. A flag that runs a program or writes a file is refused. |
| Secrets | No read of credential files. A glob, a brace or a recursive read with hidden files that reaches one counts. |

- A refusal explains the cause and the fix. It goes to `scratch/gate.log` of the effort, or to `locks/gate-home.log`.
- A refusal of one call in a parallel batch also fails the other calls of that batch. Repeat the other calls one by one.
- The gates judge a shell command by its text. They stop mistakes, not a hostile agent.
