# Customer / End-User Update

For an external reader who runs the product but does not see your code, logs, or internal tickets.
They care about three things, in order: does it work, what do I have to do, and (if it broke) why
and when will it be fixed. They do not care about your class names, PIDs, or commit hashes.

## Rules

- **Lead with their reality, not your investigation.** Open with status and, if they did work for you
  (ran a test, sent logs), a genuine thank-you. Then "what's working" before "what isn't".
- **Translate every internal term.** `cached` → "the cache service"; the `fetch --stop` command → "the
  clean-up step"; a class or a config bean → describe the behavior, not the symbol. If you would have
  to explain a term in a footnote, replace it.
- **Strip all internal identifiers.** No hostnames, IPs, file paths, commit hashes, PIDs, ports,
  internal-only ticket numbers, or colleague names. Use `[brackets]` for the recipient's name and
  your signature so a human fills them in.
- **Never blame.** Not a person, not another team, not "the previous developer". If a recent change on
  your side caused a regression, own it plainly and apologize once - that builds trust. Frame
  cross-team dependencies as "we are coordinating with the X team", never "X has not fixed Y".
- **Be honest about scope and timeline.** If the fix is partial or the work grew, say so and explain
  why in plain language. Offer to split out anything deliverable now.
- **Tell them their action.** End with explicit next steps. If there is nothing for them to do, say
  "No action required" - that is the most reassuring sentence in the document.
- **Mark it as a draft.** A customer message is reviewed by a human before it is sent.

## Template

```
# DRAFT - review/edit before sending. Placeholders in [brackets].

Subject: [Ticket/feature] - [one-line status, e.g. "interim findings and revised scope"]

Hi [name / team],

[One-sentence context + thank-you if they ran tests or sent logs.]

What's working:
- [Improvement the reader will notice, in their terms.]

What isn't resolved yet:
- [Remaining symptom, described as the reader experiences it - not the internal mechanism.]

Why [plain-language root cause - the mechanism in one short paragraph, no internal symbols]:
[Explain the cause at the level of "the system shares one X across all Y, and under load that X
cannot keep up". Enough that they understand it is real and understood, not so much that they need
your codebase to follow it.]

What the real fix looks like:
[The direction, and why it takes coordination/time if it does. Honest about what is and isn't in
your control.]

Next steps:
- [Concrete action - yours and theirs.]

[Offer: "the [smaller improvement] can be delivered independently in the meantime" and/or "happy to
walk through this on a call".]

Best regards,
[Name]
```

## Worked example (fix delivered, no action needed)

```
# DRAFT - review before sending.

## Issue
The packet capture was failing silently after a recent update - the capture process started but
exited immediately, so no capture files were produced. The test no longer crashed, but network
traces were not being collected.

## Root cause
During recent internal work on the capture-analysis feature, we added automatic quote-wrapping for
filter values containing spaces. This unintentionally affected the capture-start path too: your
correctly single-quoted filters were wrapped in a second layer of quotes, which the capture tool
rejected. Because errors on that path were not surfaced, the failure was silent.

## Fix applied
We reverted the automatic quoting so values are passed exactly as written in your configuration.
Your existing configurations work unchanged.

## Impact on your configuration
No action required. Your existing filter and ring-buffer settings work as they did before.

## Follow-up
We have raised an internal improvement ticket to make quoting behavior consistent across all capture
actions, with proper backwards compatibility, in a future release. We apologise for the inconvenience.
```

Note what is absent: no class name (`CaptureRunner`), no method name (`buildArguments()`), no internal
ticket ID, no commit hash. The reader gets the cause, the resolution, and the one fact they need ("no
action required").
