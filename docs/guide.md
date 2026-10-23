# effortkit guide

How to set up a project, run efforts, use the improvement loop, and change the kit.

## Words

- **Kit**: this repository. The generic machinery that every project shares.
- **Instance**: one deployment of the kit for one project. Its folder holds `instance.json`, the overlay, the worklog and the trees.
- **Overlay**: the project rules of an instance: project steering, prompt additions per role, project skills.
- **Effort**: one unit of work. It has a plan folder, a tree (a git worktree) or none, a branch and a supervisor session.
- **Kind**: the type of an effort. Built in: `code`, `review`, `triage`, `kit` (a change to the kit) and `overlay` (a change to the instance).
- **Workflow report**: a note from an agent or the owner on what made the work slower or worse, and what would be better.
- **Improvement round**: an effort of kind `kit` or `overlay` in which the improver triages the reports and plans the fixes.

## Set up a new project

Once per machine, from the folder of the kit:

```bash
bin/effortkit setup      # links effortkit into ~/.local/bin, then runs effortkit doctor
```

`effortkit doctor` checks Python, git, the kiro-cli version and login, tmux, rg, npx, commit signing, the kit skills and every registered instance.

Then, interactive, with the installer agent:

```bash
effortkit installer ~/efforts/<name>
```

The installer inspects the project, proposes every setting with its evidence, asks only what the repository cannot tell, installs the instance, and writes the project steering.
It writes only in the target folder and in `/tmp`, and every command that changes something asks you first.

Without the agent, in two steps:

```bash
effortkit init <git-url-or-clone> --out answers.json    # detects the settings and prints the evidence of each
effortkit install --dir ~/efforts/<name> --config answers.json
```

`effortkit init` reads the history and the build files: the default branch, the commit and ticket convention, the branch naming, the test commands, the tree setup and the commands that publish.
Review the answers before the install. `docs/config.md` describes every key, and `effortkit check <dir> --validate` checks an instance.

Then put the instance command on PATH under a name of your choice:

```bash
ln -s ~/efforts/<name>/bin/effort ~/.local/bin/<name>-effort
```

## Run an effort

1. `effort home` opens the home chat, which serves every effort. `effort start <name>` opens the chat of one effort.
2. Create the effort, or let the home chat do it: `effort new <name> --kind code [--ticket <key>]`.
3. Say what you want. The supervisor sends the explorer, the researcher and the planner.
   The planner writes `task.md` and `questions.md`. The supervisor can show them as a review page.
4. Approve the plan in the chat: `!effort approve <name>`. Only you can do this. A changed `task.md` needs a new approval.
5. The supervisor sends the developer, the tester and the reviewer. Each wave ends with a local commit. Agents never push.
6. You push and open the merge request. After the merge, the supervisor merges the fact notes of the effort into the knowledge, and you run `effort close <name>`.

Inside the chats, `effort` is the command of the instance, because the session puts the instance's `bin/` first on PATH.

## Skills

- The kit ships every skill that its agents load: its own lane and plan-review skills, and the standard skills lavish, grill-me with grilling, caveman with ultracave and megacave, asd-ste100, web-search, engineering-writeup and diagnostic-experiment-matrix.
- `effort gen` copies the skills of each role into the workspace of the instance, `.kiro/skills/`, and the agent configs name only those copies.
  So an instance works the same on every machine, and a change in `~/.kiro/skills` does not reach it.
- Every session runs with `KIRO_HOME=<instance>/.kiro-home`, which links only the kiro settings and the MCP servers of the machine.
  kiro-cli would otherwise add every skill of `~/.kiro/skills` and every file of `~/.kiro/steering` to every agent.
  A personal steering file that a project needs goes into `overlay/steering/` as a copy.
- A project skill goes into `overlay/skills/<name>/` as a copy. It replaces a kit skill of the same name.
- `effortkit skills` lists the shipped skills with their sources and licences. `skills/skills-lock.json` records them.

## The improvement loop

- Every stage ends with the duty to write notes into the one inbox, `worklog/inbox/`: a `type: workflow` note for each problem that the workflow caused (a misleading prompt, a refused command that the task needed, a missing tool), and a `type: fact` note for each durable fact about the project.
  You file a workflow note yourself with `effort report "<text>" --scope kit|overlay`, and a fact with `effort kb add <topic> <text>`.
- The gates log every refusal and the effort command logs every run, so the improver also sees friction that nobody reported.
- `effort improve` starts a round: one effort of kind `kit` for the kit notes and one of kind `overlay` for the project notes.
  The improver writes `triage.md` (a decision per note), `task.md` and `questions.md`. You approve the plan like any other.
  The developer implements it in a tree of the kit or of the instance repository, and the tester runs the kit tests.
- With `improve.trigger: on-close` (the default), `effort close` starts a round in the background when the open workflow notes reach `improve.threshold`.
- `effort close` of a round files each decided note into `worklog/improvements/done/` and the ledger.
  `effort improve stats` shows the workflow notes per effort, oldest first. The numbers should fall.
- A kit change reaches every instance after you merge it into `main` of the kit: the gate at once, the prompts after `effort gen`. The supervisor's context says when the configs are out of date.

## Layout

```
effortkit/                       the kit, repository 1
  bin/effortkit                  install, installer, check, instances, reports, selftest
  bin/effort                     the effort command; each instance has a wrapper in its bin/
  lib/effortkit/                 core, gate, cli, gen, improve, install, plan review, shell parser
  agents/*.md                    role prompt templates with {{placeholders}}
  steering/workflow-contract.md  the contract template
  skills/                        lane skills, plan review and the standard skills, with skills-lock.json
  hooks/                         commit-msg and pre-push templates
  docs/config.md                 every key of instance.json
  tests/                         the kit tests

<instance>/                      repository 2: instance.json and overlay/
  instance.json
  overlay/{steering,agents,skills}/
  worklog/                       repository 3: plan/, inbox/, knowledge/, improvements/, reference/
  product.git/                   bare clone of the project (or repo.path names your clone)
  trees/<effort>/                one worktree per effort
  .kiro/                         generated agent configs, prompts, steering, settings and the skill copies
  bin/effort, bin/effortkit      generated wrappers
  locks/                         sessions, the home gate log, the worklog lock
```

## Commands

| Command | What it does |
|---|---|
| `effort status [--collisions]` | Open efforts: stage, approval, live session, runs, branch. Open reports. |
| `effort new <name> --kind <k> [--base <ref>] [--ticket <key>] [--branch <b>]` | Plan folder, tree, branch. An existing `--branch` continues it. |
| `effort start <name>` / `effort home` | A supervisor chat. `--resume` continues, `--terse` asks for short replies. |
| `effort approve <name>` | Approves `task.md`. Owner only, in a terminal or with `!`. |
| `effort run <name> --role <r> --brief <file> [--detach]` | One headless stage. The supervisor runs this. |
| `effort wait <run-id>`, `effort logs <run-id>`, `effort attach <name>` | Results and windows of runs. |
| `effort close <name>` | Removes the tree, keeps the branch, files the reports of a round. |
| `effort report <text>`, `effort improve`, `effort improve stats` | The improvement loop. |
| `effort find <words>`, `effort kb add <topic> <text>` | Search the plans, add a knowledge entry. |
| `effort plan-review <name> [decision.md]` | A review page of the plan or of the open decisions. |
| `effort preflight <name> [--fix]`, `effort gen [--check]` | Checks, hooks and generated configs. |
| `effortkit setup`, `effortkit doctor [--instance <dir>]` | Put effortkit on PATH once per machine, and check the machine, the kit and the instances. |
| `effortkit init <repo> --out <file>`, `effortkit install --dir <dir> --config <file>` | Detect the answers of a new instance, with evidence, and install it. |
| `effortkit instances`, `effortkit reports --scope kit` | Every registered instance, and the open kit notes across them. |
| `effortkit skills [lock]` | The shipped skills, their sources and licences. `lock` records the hashes after a change. |

## Safety

- Only the owner approves a plan. The approval covers the exact `task.md` by its hash.
- Agents never push, force, reset, clean, change branches or skip hooks. A forge or MCP write is for the supervisor, after the owner said yes.
- The gate refuses reads of credential files, writes outside the zones of the role, and the forbidden commands of the config.
- The gates judge a shell command by its text. They stop mistakes, not a hostile agent.

## Tests

```bash
effortkit selftest      # or: python3 -m unittest discover -s tests -t .
```

The tests build temporary instances and a toy project, and a fake kiro-cli stands in for the model. They change nothing outside `/tmp`.

## Changing the kit

Use an effort of kind `kit` in any instance: `effort new <name> --kind kit`.
Its tree is a worktree of this repository, so live sessions keep the merged version until you merge the change.
`design.md` records the design and its open decisions.
