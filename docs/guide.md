# effortkit guide

The skills, the improvement loop, and the layout of the kit and of an instance.
The README describes the setup, the daily use and the commands.

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
  bin/effortkit                  setup, doctor, init, install, installer, check, skills, instances, selftest
  bin/effort                     the effort command; each instance has a wrapper in its bin/
  lib/effortkit/                 core, gate, cli, gen, inbox, improve, skills, detect, install, doctor, shell parser
  agents/*.md                    role prompt templates with {{placeholders}}
  steering/workflow-contract.md  the contract template
  skills/                        lane skills, plan review and the standard skills, with skills-lock.json
  hooks/                         commit-msg and pre-push templates
  docs/guide.md, docs/config.md  this guide, and every key of instance.json
  tests/                         the kit tests

<instance>/                      repository 2: instance.json and overlay/
  instance.json
  overlay/{steering,agents,skills}/
  worklog/                       repository 3: plan/, inbox/, knowledge/, improvements/, reference/
  product.git/                   bare clone of the project (or repo.path names your clone)
  trees/<effort>/                one worktree per effort
  .kiro/                         generated agent configs, prompts, steering, settings and the skill copies
  .kiro-home/                    the KIRO_HOME of the sessions: links to the machine settings only
  bin/effort, bin/effortkit      generated wrappers
  locks/                         sessions, the home gate log, the worklog lock
```
