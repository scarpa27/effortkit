<Workflow rules for every role>
- The workflow contract is `{{contract}}`. Read it when a rule is unclear.
- A gate checks every tool call. A refusal names the gate, the reason and the fix.
  Do not search for a workaround. If the rule blocks your task, report it and stop.
- Do not use the subagent tool.
- Use absolute paths in every artifact.
- Reply to the supervisor tersely: what you did, the artifact path, the open points.
  Write the artifact itself in plain, complete sentences.
</Workflow rules for every role>

<End of every stage>
1. Write your artifact in the plan folder named in your brief.
2. Write one file per new finding about the project in `findings/<UTC time>-<role>.md` of the plan folder.
   List them under `## NEW ISSUES` in your reply. Do not fix an unrelated problem, and do not widen the task.
3. Write one workflow report per problem that the workflow caused you, into `{{reports}}/<UTC time>-<effort>-<role>.md`.
   A problem is anything that cost time or gave a wrong result: a misleading prompt, a refused command that your task needed, a missing tool or skill, a missing fact, a step that you had to guess.
   Use this format:
   ```
   scope: kit | overlay | unsure
   area: prompt:<role> | gate | cli | skill:<name> | steering | config | knowledge | other
   severity: blocker | friction | idea

   ## What happened
   ## What would be better
   ## Evidence
   ```
   `kit` means the generic machinery, which every project shares. `overlay` means the rules of {{project}}.
   End your reply with `## IMPROVEMENT: <the report file names>`, or `## IMPROVEMENT: none`.
4. A durable fact about {{project}} goes into the knowledge inbox `{{knowledge_inbox}}/<UTC time>-<effort>-<role>.md`.
   Name the target topic in its first line: `target: <topic>.md`.
</End of every stage>
