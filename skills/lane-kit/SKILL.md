---
name: lane-kit
description: "Lane rules for an effort of kind kit: a change to the effortkit machinery that every instance shares - its prompts, contract, lane skills, gate, effort command or generator. Use whenever the effort kind is kit, an improvement round targets the kit, or the owner asks to change a generic agent, gate or command."
---

# Lane: kit

## What the tree is

- The tree is a worktree of the kit repository, on a branch `workflow/<effort>`.
- Live sessions keep using the main checkout of the kit until the owner merges the change.
  So a half-edited gate cannot break a running session.
- The kit is shared by every instance. A change must be generic: no project names, paths, tools or conventions.
  A project rule belongs in the overlay of its instance: propose an overlay effort instead.

## Flow

- Improvement round: improver (triage, plan), owner approval, developer, tester, reviewer.
- Direct change: explorer, planner, owner approval, developer, tester, reviewer.

## Skills

- The kit ships every skill that a role of the kit loads, in `skills/<name>/`. `effort gen` copies them into each instance.
- A new or changed skill from another source needs its entry in `skills/skills-lock.json`: the source, the version, the licence and the files.
  Then record its hash in the tree: `python3 bin/effortkit skills lock --kit <tree>`.
- A skill that one project needs belongs in that project's overlay, not in the kit.

## Tests

- The kit tests run in the tree: `python3 -m unittest discover -s tests -t .`
- A gate change needs a test with one refused call and one allowed call.
- A prompt or skill change that names a command needs that command to pass the gate for the role that runs it.
  `tests/test_prompts.py` checks this. Run it.
- An agent config change must pass `kiro-cli agent validate --path <file>` on a generated config, and the output must be empty.

## Delivery

- The developer commits each wave on the effort branch. The owner reviews the diff and merges it into `main` of the kit.
- After the merge, every instance picks up the change: the gate at once, the prompts after `effort gen`.
  The context hook tells each supervisor when its configs are out of date.
