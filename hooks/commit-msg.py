#!/usr/bin/env python3
"""effortkit commit-msg hook. effortkit renders this file: change the rules in instance.json, not here.

The gate checks a commit message before the command runs. It cannot read a message file that the same command
writes, or a message from stdin, so this hook checks the real message. Worktrees share it with their repository.
The gate keeps the rule that a commit never skips the hooks.
"""
import json
import re
import sys

RULES = json.loads(__RULES__)


def main(path: str) -> int:
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    # A verbose commit appends the diff below a scissors line. Comment lines are not part of the message.
    text = re.split(r"(?m)^# -+ >8 -+$", text)[0]
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    subject = next((line for line in lines if line.strip()), "")
    body = "\n".join(lines)
    problems = []
    if not re.match(RULES["subject_regex"], subject):
        problems.append(f"the subject must look like {RULES['subject_help']!r} (rule {RULES['subject_regex']!r}). "
                        f"Got: {subject[:80]!r}")
    if RULES.get("forbid_coauthor") and re.search(r"(?im)^co-authored-by:", body):
        problems.append("the message has a Co-authored-by line. Commits carry no agent co-author.")
    if RULES.get("forbid_dashes") and re.search("[\u2013\u2014]", body):
        problems.append("the message has an em dash or an en dash. Use '-'.")
    for p in problems:
        print(f"\ncommit-msg REFUSED: {p}\n", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
