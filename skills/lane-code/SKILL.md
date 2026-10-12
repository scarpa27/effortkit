---
name: lane-code
description: "Lane rules for an effort of kind code: a change to the project, a new feature or a bug fix, with its tests. Use whenever the effort kind is code, or the owner asks for a change, a feature or a fix in the project."
---

# Lane: code

## Flow

- Feature or change: explorer, planner, owner approval, developer, tester, reviewer.
- Bug with logs or a reproduction: debugger first, then planner.
- A symptom that can be an upstream bug: researcher before debugger.
- Use explorer before planner, unless a current `exploration-brief.md` exists.
- reviewer `REQUEST_CHANGES` goes back to developer. After three rounds, stop and ask the owner.

## Before planning

- Read the project steering and the knowledge topic that matches the task.
- The planner plans the tests with the code.

## Delivery

- The developer commits after each wave, on the effort branch.
- The owner pushes and opens the merge request.
- After the merge, merge the knowledge inbox entries of the effort, then the owner closes the effort with `effort close <effort>`.
