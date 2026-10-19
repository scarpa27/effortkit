# Cross-Team Handoff (DevOps / Platform / another dev team)

For engineers on another team who must act on this but have none of your context. This is the most
detailed artifact. Its job is to transfer enough understanding that they can investigate or fix
without you in the room - and to ask them the specific questions only they can answer. Under-detailing
here just bounces the problem back with "can you give more info?".

## Rules

- **Full technical detail is welcome.** Commands, PIDs, ports, commit hashes, log excerpts, before/after
  - include them. This reader wants depth, not a summary.
- **Open with a header block:** For / From / Date, then the problem as originally reported (quote the
  customer or reporter verbatim - it anchors the reader in the symptom).
- **Explain the mechanism, then show how you verified it.** Walk through what happens technically, then
  give the reproduction (exact commands) and the evidence (the log lines / PID-port changes that prove
  it). Verification is what makes the other team trust your diagnosis.
- **Label theories and tie each to a question.** When the cause depends on something they own (how
  things are deployed, configured, isolated), lay out theories A/B/C/D and, for each, the specific
  fact that would confirm or refute it. Then collect those into a numbered "questions for you" list.
- **Ask specific, answerable questions.** "How are the test instances deployed - separate pods or one
  shared pod?" beats "can you look into the environment?". Specific questions get specific answers.
- **Offer fixes on their side of the line.** Propose the platform/config-level options you can see,
  clearly marked as "no code change needed on our side", so they have a menu to react to.
- **End with file references.** Logs, source files, repro suite, relevant commits - so they can dig in
  independently.

## Template

```
# [Title - the failure in one line]

## For: [team / role]   From: [your team]   Date: [date]

## 1. The problem (as reported)
[The symptom, with a verbatim quote from the reporter/customer.]

## 2. What happens technically
[The mechanism. Components, sequence, the race/bug. Diagrams-in-text/timelines welcome.]

## 3. How we verified
Reproduction:
    [exact commands]
Evidence:
    [log lines, PID/port changes, before/after - the proof]

## 4. Current fix and its limitation
[What you changed on your side, and why it is not sufficient / why you need them.]

## 5. Questions for [team]
[Numbered, specific, answerable. Group theories A/B/C/D here if the cause depends on their domain.]

## 6. Possible fixes on your side (no code change on ours)
Option 1: [...]
Option 2: [...]

## 7. References
[Log paths, source files, repro suite, commit hashes.]
```

## Worked example (abridged)

```
# Export Failure with >5 Parallel Workers

## For: DevOps (architecture/deployment)   From: Export service team   Date: 2026-06-25

## 1. The problem (as reported)
Exports fail intermittently when more than 5 workers run in parallel on the new architecture; the
export files are empty. Key statement from the reporter: "The same job with the same hardware works
flawlessly with 8 parallel workers on the old architecture."

## 2. What happens technically
`cached` is a daemon on the build host listening on 3 ports (control/data/live). When a worker runs
`fetch`, the tool reuses an existing daemon if present, else starts one. When it runs `fetch --stop`,
the tool kills the daemon if it believes no sessions remain - but it only knows about its own
sessions. With 6+ parallel workers sharing one daemon, the first to finish kills it for everyone.

## 3. How we verified
Reproduction:
    run-workers 6 export-single.yaml          # without fix
Evidence (failing run): daemon PID changes 11494 -> 28361 between two fetch starts (another worker
killed the original); 5/6 workers then log "cached process not found".
With dedicated per-worker ports: all 6 workers keep their own daemon PID throughout; none killed.

## 4. Current fix and its limitation
The export service starts a dedicated daemon per worker, but it requires a unique --cache-port per
worker - manual config users never needed before.

## 5. Questions for DevOps
1. How are the workers deployed - separate pods, or one shared pod?
2. Is there a shared build host? How many workers share it?
3. Is `cached` started anywhere in entrypoint scripts or helm charts?
Theory A (shared vs dedicated host): old = pod per worker = own daemon; new = shared host.
Q1+Q2 confirm or refute this.

## 6. Possible fixes on your side (no code change on ours)
Option 1: give each worker its own isolated workspace (restores old behavior).
Option 2: pre-start a persistent daemon in the entrypoint so `fetch --stop` cannot kill it.

## 7. References
Customer logs: <log folder of the report>   Source: CacheDaemonManager.java, ExportService.java
Architecture merge commit: 3f2a9c1d7e04...
```
