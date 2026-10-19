---
name: engineering-writeup
description: "Turn a technical investigation, root-cause analysis, or completed fix into an audience-targeted written communication. Use this whenever you need to communicate engineering findings to someone other than yourself: a customer status update, a Jira/issue-tracker comment, a cross-team or DevOps handoff, or a follow-up/improvement ticket. Trigger it on phrases like 'draft a customer update', 'write a Jira comment for this', 'summarize these findings for the customer', 'hand this off to the DevOps/platform team', 'write an improvement ticket', 'explain the root cause to a specific audience', 'write up what we found', or any time investigation notes need to become a message someone else will read. The same facts get framed very differently per audience, and getting the framing, jargon level, and anonymization wrong is costly - so reach for this skill even when the user just says 'write it up'."
---

# Engineering Writeup

A debugging session, root-cause analysis, or fix produces a pile of internal facts: PIDs, ports,
commit hashes, class names, log excerpts, theories, reproduction commands. The hard part is rarely
the facts. It is retelling them for a specific reader who needs a specific subset, at a specific
level of detail, in language they can act on. The same root cause becomes four very different
documents depending on whether the reader is a customer, a teammate triaging in a ticket, another
team you are handing off to, or a future engineer reading a follow-up ticket.

This skill exists because that translation step is done from scratch every time, and the failure
modes are expensive: leaking internal codenames or PII to a customer, blaming another team in
writing, burying the one thing the reader must do, or shipping a "ticket" that no one else can
understand without the original context in your head.

## The core idea

**Identify the reader first, then choose what to include, exclude, and how to frame it.** Everything
else follows from the reader. Do not start writing prose until you know who it is for.

## Step 1 - Identify the audience and artifact

Match the request to one of the four artifact types. If the user did not say, infer from cues
("customer", a customer's name or team → customer; "Jira", "comment", "the ticket" → ticket comment;
"DevOps", "platform", another team's name, "hand off" → cross-team handoff; "improvement", "follow-up",
"file a ticket for later" → follow-up ticket). If it is genuinely ambiguous, ask one short question
rather than guessing - the framing rules differ enough that guessing wrong wastes the whole draft.

| Reader | Artifact | They want | Reference |
|--------|----------|-----------|-----------|
| External customer / end user | Customer update | Honest status, plain language, what (if anything) they must do | `references/customer-update.md` |
| Teammates watching the ticket | Issue-tracker comment | Dense status: result → root cause → next step | `references/ticket-comment.md` |
| Another team (DevOps, platform, tooling) | Cross-team handoff | Full technical detail + specific answerable questions | `references/cross-team-handoff.md` |
| Future engineers / backlog | Follow-up / improvement ticket | Self-contained problem + proposal + migration + priority | `references/followup-ticket.md` |

Read the matching reference file for the template, the inclusion/exclusion rules, and a worked
example before you write. Each reference is short and built from a real example.

## Step 2 - Gather the source facts (do not invent)

A writeup is only as trustworthy as the investigation behind it. Pull the raw material from what
already exists - the plan folder of the effort (`investigation.md`, `research-brief.md`, `review.md`,
`status.md`, `findings/`), the diagnosis from a triage skill, the diff/commit, the ticket. Assemble these before
writing:

- **Result / current status** - what is the state right now? (passing, partially fixed, root-caused but unfixed)
- **Root cause** - the actual mechanism, stated in one or two sentences.
- **Evidence** - the specific facts that prove it (log lines, PIDs/ports, before/after, repro commands).
- **The fix or proposal** - what was changed, or what should change, and its limitation.
- **What the reader must do** - action, decision, or "nothing required".
- **References** - files, commits, tickets, log paths.

If a needed fact is not in the source material, treat it as a gap: write the rest and flag the gap
explicitly (e.g. "[confirm: was the daemon started externally?]") rather than inventing a plausible
value. A confident-sounding fabricated detail is worse than a visible question, because the reader
cannot tell it is a guess.

## Step 3 - Draft using the reference template

Follow the template in the chosen reference. The four share a backbone (status, root cause, action)
but differ on three axes that you must tune to the reader:

1. **Jargon and identifiers.** Internal artifacts (ticket comment, handoff) keep PIDs, ports, class
   names, commit hashes - they help teammates act fast. Customer artifacts translate them
   ("`cached`" → "the cache service", "the `fetch --stop` command" → "the clean-up step") or drop them.
   Never put a raw internal class name, host name, file path, or commit hash in a customer document.
2. **Blame and attribution.** Internal artifacts can name the regressing commit or component plainly
   because the goal is to fix it. Customer artifacts never blame a person or another team; frame
   cross-team dependencies as "we are coordinating with X". Owning a regression honestly ("a recent
   change on our side caused this") builds more trust than deflecting.
3. **Detail and length.** A ticket comment is the shortest thing that still carries the result, cause,
   and next step. A handoff is exhaustive - theories, questions, commands, file refs - because the
   reader has none of your context. A customer update is medium and leads with what they care about
   (does it work, what do I do), not with the mechanism.

## Cross-cutting principles

- **Lead with what the reader needs, not the chronology of your investigation.** They do not want the
  story of how you found it; they want the conclusion and their next move up top.
- **One artifact, one reader.** Do not try to satisfy a customer and the platform team in the same
  document. If the user needs both, write both.
- **Anonymize external-facing drafts.** Replace real names with `[brackets]` placeholders, strip
  internal hostnames/IPs/paths/node-IDs, and mark the draft so it is reviewed before sending
  (a `# DRAFT - review before sending` header). This mirrors how these drafts are handled in practice
  and prevents an internal detail from reaching a customer by accident.
- **Be honest about uncertainty and scope.** If the timeline grew or the fix is partial, say so
  plainly. A surprised stakeholder later is worse than a disappointed one now.
- **Match the platform's format.** Plain text or light markup for issue trackers (heavy markdown often
  renders badly in Jira); clean markdown for a handoff doc; email-style prose for a customer message.

## Self-check before delivering

Before you hand the draft back, verify against the reader:

- Does the first paragraph already tell the reader the status and their action?
- Is every claim traceable to the source facts (no invented numbers, names, or causes)?
- For customer drafts: zero internal class names / hostnames / paths / commit hashes / PII? No blame?
  DRAFT marker and `[placeholders]` present?
- For handoffs: are the questions specific and answerable, and did you include repro commands and file
  references so the other team can act without you?
- For follow-up tickets: could someone with no context understand the problem, the proposal, the
  migration impact, and the priority?
- Is it the shortest version that still does the job for this reader?

If you wrote more than one artifact, keep them in separate files/sections so they are never sent to
the wrong audience.
