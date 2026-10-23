# effortkit

effortkit is an agentic workflow for kiro-cli.
You can deploy it to any software project.

## Purpose

- effortkit lets a team of AI agents do software work in a project.
  One person, the owner, controls the work.
- Each unit of work is an effort.
  An effort has a plan folder, a branch and its own git worktree.
- A supervisor agent runs the efforts.
  It gives each task to a specialist agent: an explorer, a researcher, a planner, a developer, a tester, a reviewer, a debugger or an improver.
- The agents can work on many efforts at the same time.
  The agents of one effort change only the worktree of that effort.
- The owner approves each plan before an agent changes the code.
  A changed plan needs a new approval.
- A gate checks every tool call before the call runs.
  The gate refuses a call that:
  - writes outside the folders of the agent,
  - pushes to a remote,
  - discards work, for example `git reset --hard`,
  - reads a credential file.
- The agents never push.
  The owner pushes, and opens the merge request or the pull request.
- The workflow has an improvement loop.
  - The agents write a note about each problem that the workflow causes them.
  - The gate records each refusal.
  - An improver agent reads these records.
    Then it writes a plan for a fix.
  - The owner approves the plan.
    Then a developer agent makes the change.
- One kit serves many projects.
  The kit holds the generic rules, the agent prompts and the skills.
  Each project adds its own rules in one configuration file and one overlay folder.
- Each project keeps its own copy of every skill that its agents use.
  Thus the project works the same on every machine.

## Requirements

- Linux, Python 3.9 or later, git and kiro-cli.
- Optional: tmux for stages in the background, rg for searches, and npx for the review pages.
- `effortkit doctor` checks these tools.

## Start

1. Run `bin/effortkit setup` once on each machine.
   This adds the `effortkit` command to your PATH.
   Then it checks the tools.
2. Run `effortkit installer <folder>` to set up a project.
   The installer agent examines the project.
   Then it asks you only what the project does not show.
3. Run `<folder>/bin/effort home` to start the supervisor of the project.

## More information

- `docs/guide.md`: how to use the kit, its commands and its layout.
- `docs/config.md`: every setting of a project.
