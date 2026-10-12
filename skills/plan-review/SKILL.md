---
name: plan-review
description: "Show a planner's task.md and questions.md, or the owner's open choices in decision.md, as a review page, collect the answers and comments, and record them. Use when a plan is ready for the owner, when questions.md holds questions, when decision.md holds open decisions (stage AWAITING_DECISION), or when the owner asks to review a plan visually."
---

# Plan review

## Steps

1. Build the page from the plan folder:
   ```bash
   effort plan-review <effort>               # task.md and questions.md
   effort plan-review <effort> decision.md   # the open decisions
   ```
   It prints the page path, under `<plan folder>/review/`.
   Do not write a review page by hand.
   If the page does not show a decision as a card, fix the format of `decision.md` (below) and build the page again.
2. Open it for the owner. With Lavish (optional, needs `npx`):
   ```bash
   LAVISH_AXI_TELEMETRY=0 npx -y lavish-axi <page>
   ```
   Tell the owner the URL that this command prints.
   Without Lavish, give the owner the page path. The page has a "Copy all answers" button, and the owner pastes the text into the chat.
3. With Lavish, wait for the feedback in the foreground. The poll stays silent until the owner sends:
   ```bash
   LAVISH_AXI_TELEMETRY=0 npx -y lavish-axi poll <page>
   ```
4. Record the answers word for word, one block per question or decision ID:
   - For `task.md` and `questions.md`: in `answers.md` of the plan folder.
   - For `decision.md`: in `decision.md`, under `## Owner answers <date and time>`.
5. If an answer changes the plan, run the planner again with the answers. Then build a new page and repeat.
6. When the plan is final, tell the owner: `!effort approve <effort>`.

## The format of decision.md

```markdown
## D1: <the decision, in a few words>

- <context, one sentence per line>

| Option | <a column that compares the options> |
| --- | --- |
| 24 h | ... |
| 7 days | ... |

- Recommendation: 24 h.
```

- A section is a decision when its heading is `## <ID>: <title>` and it has two or more options.
- Options come from bullets `- (a) <text>`, `- A: <text>` or `- Option A: <text>`.
  Without such bullets, they come from the first column of the first table of the section.
- The `Recommendation:` line names the option by its letter or the start of its text.
- A settled decision goes into a section without an ID, for example `## Decided`.

## Rules

- The page never approves the plan. A prompt from a page reaches you, the agent, and an agent never approves its own plan.
- Never run `lavish-axi share`. It publishes the page to a third-party host.
