# Follow-up / Improvement Ticket

For the backlog and whoever picks this up later - possibly you in six months, possibly someone who
has never seen the original problem. The defining constraint is **self-containment**: it must stand
on its own, because the context living in your head right now will be gone. Its job is to capture a
known-but-deferred improvement so it is not lost and can be prioritized against other work.

## Rules

- **Be self-contained.** Assume zero memory of the original investigation. State the problem from
  scratch, including the bit of background needed to understand why it matters.
- **Separate problem from proposal.** First establish what is wrong / inconsistent / risky and why.
  Then propose the solution. Mixing them makes it hard to disagree with the fix while accepting the
  problem.
- **State the current state honestly,** including any workaround already in place - this tells the
  reader the urgency (a working workaround usually means medium priority, not urgent).
- **Spell out migration impact.** If the change breaks existing usage/config, show a concrete
  before/after and say who is affected. Silent breakage discovered later erodes trust.
- **Assign a priority with a one-line justification.** "Medium - functional workaround exists, but the
  inconsistency is an onboarding and maintenance risk." The justification matters more than the label.
- **Add the tracker metadata the reader's tool needs to route it.** A short header with Type, Priority,
  Component, and Related tickets lets the backlog triage and link the work without opening it. These are
  the fields a tracker actually sorts and filters on.
- **Give acceptance criteria when the work is concrete enough.** A short checklist of "done when..."
  turns a deferred idea into something a future engineer can verify they finished. Skip it only when the
  proposal is still too open-ended to bound.

## Template

```
# [Concise title - what should change]

**Type:** [Improvement / Tech Debt / Bug]   **Priority:** [level + half-line reason]
**Component:** [area/class]   **Related:** [tickets this follows from or links to]

## Summary
[The problem in 2-4 sentences. What is inconsistent / missing / risky, and the consequence.]

## Current state
[How it behaves today, including any workaround. Enough that the reader understands the status quo
without the original context.]

## Proposed solution
[The change, as concrete steps or options. Include any new property/API/flag and its default.]

## Migration impact
[Who/what is affected and how. Concrete before/after if it breaks existing usage. "None" if backwards
compatible.]

## Acceptance criteria
[Optional but recommended when concrete: a short "done when..." checklist a future engineer can verify.]

## Priority
[Level] - [one-line justification grounded in risk/impact, not gut feel.]
```

## Worked example

```
# Unify Option Value Handling Across Capture Actions

## Summary
The capture step's actions handle option-map values inconsistently: START_CAPTURE/PARSE use raw
concatenation (the user must quote values with spaces), while MATCH auto-wraps spaced values in
quotes (the user must NOT quote). The same property behaves differently depending on which
action reads it, which is undocumented and surprising.

## Current state
After the recent regression fix, all actions work correctly, but the quoting convention is split:
capture configs must quote (`value="'not (udp or tcp ...)'"`), match configs must not
(`value="http.response.code in {200,301,404}"`). There is no documentation explaining the distinction.

## Proposed solution
1. Unify all actions to raw concatenation (user always handles quoting).
2. Add a `rawArguments` list property for repeated flags and complex arguments.
3. Add a release-note migration entry and document the quoting convention in the Configuration Guide.

## Migration impact
Configs using MATCH with bare spaced values would need quotes added:
    before: value="http.response.code in {200,301,404}"
    after:  value="'http.response.code in {200,301,404}'"

## Priority
Medium - a functional workaround exists, but the inconsistency is a maintenance and onboarding risk.
```

Note that the example never refers to "the bug we just fixed" or "as discussed" - every fact a reader
needs is restated, because the reader may have no access to that conversation.
