# Issue-Tracker Comment (Jira / GitLab / etc.)

For teammates following the ticket. They share your context and vocabulary, so this is the densest
artifact: the shortest text that still carries result, cause, and next step. Its job is to let
someone scanning the ticket understand the current state in 20 seconds without opening logs.

## Rules

- **Status first.** The first sentence states the current result (passing / partially fixed /
  root-caused but unfixed / blocked). A reader who only reads one line should still know where things
  stand.
- **Then cause, then implication, then next.** Root cause in one or two sentences. The implication
  (what it means for the fix or the ticket's scope). The next step or current activity.
- **Keep internal detail, but only load-bearing detail.** PIDs, ports, class names, commit hashes are
  fine when they let a teammate act - but only include the ones that matter. A comment is not a log
  dump.
- **Plain text or light markup.** Many trackers render heavy markdown badly. Short paragraphs or a few
  bullets beat nested headers and tables.
- **No fluff.** No greeting, no sign-off, no "I hope this helps". Teammates want signal.
- **Keep it short.** As a rough calibration, a status comment usually lands around 150-300 words. If you
  are past ~350, you are probably including detail that belongs in the ticket body or a handoff doc, not
  in a status comment - move it there and link instead.
- **State scope changes explicitly.** If the finding changes the ticket's scope or estimate, say so -
  that is often the most important thing in the comment.

## Template

```
[Result/status in one sentence - what is the state right now.]

Root cause: [the mechanism, 1-2 sentences, with the load-bearing internal detail.]

Implication: [what this means - e.g. "cannot be fixed from our side alone", "fix is in review",
"original approach is a dead end and should be reverted".]

[Positive note if any - what IS working, so the comment is not all-negative.]

Current status / next: [what is happening now or the next concrete step.]
```

## Worked example

```
Customer's 8-worker run on the fix branch has been analyzed. Results: 3/8 workers produce complete
exports in both runs; the other 5/8 produce files but are missing the first records (e.g. the header
batch), causing the export checks to fail.

Root cause: The pre-allocated per-worker cache ports do not isolate the workers as intended.
The `fetch` tool reuses a single shared `cached` daemon for all workers under the same user on the
same host, regardless of the per-worker ports we set. Under 8 parallel sessions that shared daemon
cannot keep up and early records are dropped.

Implication: The contention cannot be fully resolved by code changes on our side alone; it needs
environment-level isolation (separate user per worker, or separate cache endpoint).

Positive note: the DEBUG log-level downgrade for the empty-batch messages is working as expected.

Current status: investigating approaches (environment isolation, options of the fetch tool). Will
update once next steps are determined.
```

Note the density: every sentence carries a fact a teammate needs. It keeps internal terms (`fetch`,
`cached`, the header batch) because the readers know them, but it is four short paragraphs, not a
report.
