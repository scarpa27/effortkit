"""Render the commit-msg and pre-push hooks for one repository, install them, and report their state."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import core

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def render(inst: core.Instance, repo: Path) -> dict[str, bytes]:
    rules = inst.commit_rules(repo)
    re.compile(rules["subject_regex"])  # A broken rule must fail here, not in every later commit.
    commit = (core.KIT / "hooks/commit-msg.py").read_text(encoding="utf-8")
    commit = commit.replace("__RULES__", repr(json.dumps({k: rules[k] for k in sorted(rules)})))
    push = inst.push_rules(repo)
    branches = [b for b in push.get("protected_branches", []) if BRANCH_RE.match(b)]
    if len(branches) != len(push.get("protected_branches", [])):
        raise ValueError(f"push.protected_branches holds a name that is not a plain branch name: {push['protected_branches']}")
    pre_push = (core.KIT / "hooks/pre-push.sh").read_text(encoding="utf-8")
    pre_push = pre_push.replace("__PROTECTED__", " ".join(branches)).replace("__MAX_TAGS__", str(int(push.get("max_tags", 2))))
    return {"commit-msg": commit.encode(), "pre-push": pre_push.encode()}


def state(inst: core.Instance, repo: Path) -> str:
    """"ok", "missing", "not executable", "out of date" or "no repository", for the commit-msg hook of repo."""
    common = core.git_common_dir(repo)
    if common is None:
        return "no repository"
    hook = common / "hooks/commit-msg"
    if not hook.is_file():
        return "missing"
    if not os.access(hook, os.X_OK):
        return "not executable"
    try:
        return "ok" if hook.read_bytes() == render(inst, repo)["commit-msg"] else "out of date"
    except OSError:
        return "missing"


def install(inst: core.Instance, repo: Path) -> list[str]:
    """Write the hooks into the common git directory of repo. Return the names that changed."""
    common = core.git_common_dir(repo)
    if common is None:
        raise FileNotFoundError(f"{repo} is not a git repository")
    (common / "hooks").mkdir(parents=True, exist_ok=True)
    changed = []
    for name, content in render(inst, repo).items():
        dest = common / "hooks" / name
        if not dest.is_file() or dest.read_bytes() != content:
            dest.write_bytes(content)
            changed.append(name)
        dest.chmod(0o755)
    return changed
