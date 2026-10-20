---
name: lane-triage
description: "Lane rules for an effort of kind triage, which has no tree: log analysis, research, questions that need no code change, and consolidation of several efforts. Use whenever the effort kind is triage, or the task is to analyse, answer, compare or summarise."
---

# Lane: triage

- A triage effort has no tree.
  It runs from the instance root and writes only its own plan folder and the inbox.
- Logs or a symptom: debugger, with the log paths in the brief.
  If the cause is in the code, propose a code effort for the fix.
- External facts: researcher, with one named question per call.
- Old work: `effort find <words>` searches the plan folders.
  Record the related efforts, one per line, in `related.md` of this plan folder.
- Consolidation: read the related efforts, and write one summary into this effort's plan folder.
  Do not edit the files of the other efforts.
