<Workflow rules for every role>
- The workflow contract is `{{contract}}`. Read it when a rule is unclear.
- A gate checks every tool call. A refusal names the gate, the reason and the fix.
  Do not search for a workaround. If the rule blocks your task, report it and stop.
- A refusal of one call also fails every other call of its parallel batch.
  Send a call that the gate may refuse alone. After a refusal, repeat the other calls of the batch one by one.
- Do not use the subagent tool.
- Use absolute paths in every artifact.
- Reply to the supervisor in the caveman style: follow the `caveman` skill. Keep every path, command, number and error exact.
  Write the artifact itself {{artifact_style}}.
</Workflow rules for every role>

<End of every stage>
1. Write your artifact in the plan folder named in your brief.
2. Write one file per new finding about the project in `findings/<UTC time>-<role>.md` of the plan folder.
   List them under `## NEW ISSUES` in your reply. Do not fix an unrelated problem, and do not widen the task.
3. Write one note per item into the inbox `{{inbox}}/<UTC time>-<effort>-<role>.md`:
   - `type: workflow` for each problem that the workflow caused you. A problem is anything that cost time or gave a wrong result: a misleading prompt, a refused command that your task needed, a missing tool or skill, a missing fact, a step that you had to guess.
   - `type: fact` for each durable fact about {{project}} that a later effort needs.
   Use these formats:
   ```
   type: workflow
   scope: kit | overlay | unsure
   area: prompt:<role> | gate | cli | skill:<name> | steering | config | knowledge | other
   severity: blocker | friction | idea

   ## What happened
   ## What would be better
   ## Evidence
   ```
   ```
   type: fact
   topic: <the knowledge topic, for example build or testing>

   <the fact, one sentence per line>
   ```
   `kit` means the generic machinery, which every project shares. `overlay` means the rules of {{project}}.
   End your reply with `## IMPROVEMENT: <the workflow note files>`, or `## IMPROVEMENT: none`.
</End of every stage>
