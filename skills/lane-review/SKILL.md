---
name: lane-review
description: "Lane rules for an effort of kind review: review somebody's branch or merge request in a read-only tree, and prepare the review. Use whenever the effort kind is review, or the owner asks to review a branch, a merge request or a pull request."
---

# Lane: review

## Setup

- The tree is detached at the tip of the branch under review:
  `effort new <name> --kind review --base origin/<source-branch>`.
- The review compares against the target branch, normally the default base.
  Use `git diff <target>...HEAD` to see only the changes of the branch.
- Nothing in this tree is changed or committed.

## Flow

- reviewer reviews the change against the code, the conventions and the tests, and may run the tests of the touched area.
- For a large change, two reviewers can work in parallel, each on named files. They write `review-1.md` and `review-2.md`.
- The supervisor merges them into one draft for the owner.

## Posting

- No specialist posts a review. A forge write is for the supervisor only.
- The supervisor shows the draft to the owner, and posts it only after the owner says yes for this review.
  A post is visible to the whole team, and it cannot be taken back cleanly.
