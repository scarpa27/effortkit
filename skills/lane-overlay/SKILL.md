---
name: lane-overlay
description: "Lane rules for an effort of kind overlay: a change to this instance only - instance.json (test commands, commit rule, forbidden commands, tester globs, models, tools) and the overlay (project steering, prompt additions per role, project skills). Use whenever the effort kind is overlay, an improvement round targets the overlay, or the owner asks to change a project rule of the workflow."
---

# Lane: overlay

## What the tree is

- The tree is a worktree of the instance repository, on a branch `workflow/<effort>`.
  It holds `instance.json` and `overlay/`. The worklog, the trees and the generated `.kiro` are not in it.
- Live sessions keep the current rules until the owner merges the change and runs `effort gen`.

## What goes where

- A fact that every role needs: `overlay/steering/<topic>.md`.
- A rule for one role: `overlay/agents/<role>.md`. The generator appends it to the kit prompt of that role.
- A repeated procedure: a skill in `overlay/skills/<name>/SKILL.md`. Copy a skill from another place into the overlay. Never point at it.
  A skill of the overlay replaces the kit skill of the same name. `skills.<role>` gives it to one role only.
- A command rule: `instance.json` - `tests.patterns`, `forbidden_commands`, `tester_globs`, `commit`, `push`.
  `docs/config.md` in the kit describes every key.
- A fact about the project code, not about the workflow: a fact note in the inbox, not the overlay.

## Check

- Validate the tree before the review: `effortkit check <tree>`.
  It loads `instance.json`, renders every prompt and config in memory, and reports each error.
- A new test pattern or forbidden command needs one example command that matches and one that does not, in `dev-notes.md`.

## Delivery

- The developer commits each wave on the effort branch.
- The owner merges the branch into `main` of the instance repository, then runs `effort gen`.
