# effortkit design record

## 1. Origin

- effortkit is the generic core of an earlier agentic workflow that served one project.
- It keeps: efforts with a plan folder, a tree and a branch; the home and effort supervisors; headless stages with `effort run`; the approval by hash; the gate with its shell parser; the commit-msg and pre-push hooks; the knowledge inbox; the review pages.
- It leaves out every rule of that project.
- Each dropped rule that a project still needs comes back as config (`tests.patterns`, `forbidden_commands`, `tree_setup`, `secrets`) or as overlay text.

## 2. Layers

| Layer | Holds | Changes through |
|---|---|---|
| Kit | prompts, contract, lane skills, gate, effort command, generator, defaults | an effort of kind `kit`, merged by the owner into `main` of the kit |
| Instance | `instance.json` and `overlay/` | an effort of kind `overlay`, merged by the owner into `main` of the instance repository |
| Worklog | plans, knowledge, workflow reports, ledger | the agents (plan folders, inboxes) and the effort command (records, snapshots) |
| Generated | `.kiro/` and `bin/effort` of an instance | `effort gen`, automatic at session start when the inputs changed |

- Live sessions use the merged kit and the merged instance only. A change under work lives in a tree, so a half-edited gate cannot break a running session.
- The generated prompts hold absolute paths, because an agent needs them, and so the generated files are per instance and never tracked.

## 3. The improvement loop

- Sources: the reports that the agents write at the end of each stage, the reports of the owner (`effort report`), the gate refusals, and the failed or lost runs.
- A round triages the reports of one layer. The improver writes a decision per report into `triage.md`, and a normal plan. The owner approves the plan like any other.
- `effort close` of a round moves each decided report to `done/<round>/` and appends one ledger line. A deferred report stays in the inbox.
- The ledger keeps the reasons of rejected reports, so a later round does not accept the same idea again without new evidence.
- The trigger is `on-close` with a threshold, or `manual`. A round never starts while another round is open.
- The measure is the number of reports per effort over time: `effort improve stats`.

## 4. Measured facts that the design depends on

From measurements with kiro-cli 2.31.1 and 2.33.1, on Linux:

- A trusted tool still runs the `preToolUse` hook, and a hook exit 2 blocks it. A trusted write ignores `allowedPaths`, so the gate enforces the paths.
- An untrusted shell with `allowedCommands` and `denyByDefault` works headless: the matching command runs, the other fails cleanly.
- kiro-cli refuses a heredoc, a command substitution and some options before it reads `allowedCommands`.
- A subagent keeps the directory and the environment of its parent. An `export` in one shell call reaches neither the hook nor the next shell call.
- `agentSpawn` does not fire for a headless session, so the context hook uses `userPromptSubmit`.
- A refusal of one call in a parallel batch fails the other calls of the batch.
- `kiro-cli agent validate` can print an error and exit 0, so any output counts as a failure.
- On Windows, a `preToolUse` exit 2 does not block (kiro issue 8264, open on 2026-09-23). effortkit supports Linux and macOS only.

## 5. Open decisions for the owner

## D1: Who approves an improvement plan

- Today the owner approves every plan, also of a round. The loop is automatic up to the plan.

| Option | Effect |
| --- | --- |
| A: the owner approves every round | Safe. A round waits for the owner. |
| B: auto-approve overlay text changes only | Faster for prompt and steering fixes. A wrong rule reaches the agents without review. |

- Recommendation: A.

## D2: Where kit reports from several instances meet

- Today each instance triages its own kit reports. `effortkit reports --scope kit` lists them across instances.

| Option | Effect |
| --- | --- |
| A: per instance, as today | Simple. Two instances can fix the same kit problem twice. |
| B: one kit round reads the kit reports of every registered instance | One fix per problem. The round must file reports in other instances' worklogs. |

- Recommendation: B, after two instances exist.
