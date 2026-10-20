"""Sandboxes for the kit tests. Nothing here touches a real instance, the real kit repository or the registry.

FakeInstance writes an instance by hand, with fake trees and no git, for the gate tests.
RealInstance installs an instance from a toy project with the real installer, for the effort command tests.
A fake kiro-cli on PATH stands in for the model, so no test makes a model call.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(os.path.realpath(__file__)).parents[1]
sys.path.insert(0, str(KIT / "lib"))
from effortkit import core, install  # noqa: E402

GATE = KIT / "lib/effortkit/gate.py"
EFFORT = KIT / "bin/effort"
EFFORTKIT = KIT / "bin/effortkit"

CONFIG = {
    "effortkit": 1,
    "name": "toy",
    "description": "A toy project",
    "repo": {"url": "/nonexistent/toy.git", "default_base": "origin/main"},
    "ticket": {"regex": r"^TOY-\d+$", "example": "TOY-12"},
    "commit": {"subject_regex": r"^(?:TOY-\d+: |\[nojira\] )\S", "subject_help": "TOY-NNN: <subject>",
               "forbid_coauthor": True, "forbid_dashes": True},
    "tests": {"commands": ["python3 -m pytest <path>", "make test"]},
    "forbidden_commands": [{"pattern": r"^make deploy\b", "reason": "make deploy publishes the package.",
                            "fix": "The owner deploys."}],
}


def git_env(base: Path) -> dict:
    """An environment with a private git config: no signing, a fixed identity."""
    cfg = base / "gitconfig"
    if not cfg.exists():
        cfg.write_text("[user]\n\tname = Test\n\temail = test@example.com\n[commit]\n\tgpgsign = false\n"
                       "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("EFFORTKIT_")}
    env.update(GIT_CONFIG_GLOBAL=str(cfg), GIT_CONFIG_NOSYSTEM="1", XDG_CONFIG_HOME=str(base / "xdg"))
    return env


def sh(*args, cwd=None, env=None, check=True, input=None):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True, input=input)
    if check and p.returncode != 0:
        raise AssertionError(f"{args} failed ({p.returncode}): {p.stderr or p.stdout}")
    return p


class FakeInstance:
    """Efforts e1 and e2 (code, with trees), t1 (triage, no tree), k1 (kit) and o1 (overlay)."""

    def __init__(self, config: dict | None = None):
        self.dir = Path(tempfile.mkdtemp(prefix="ek-test-"))
        self.root = self.dir / "inst"
        cfg = core.merge(CONFIG, config or {})
        for d in ("worklog/plan", "worklog/inbox", "worklog/knowledge", "worklog/reference",
                  "locks", "trees", ".kiro/agents", "overlay/steering", "overlay/agents", "product.git"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        (self.root / "instance.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (self.root / "worklog/knowledge/project.md").write_text("# project\n")
        repos = {"code": str(self.root / "product.git"), "kit": str(core.KIT), "overlay": str(self.root)}
        for name, kind in (("e1", "code"), ("e2", "code"), ("t1", "triage"), ("k1", "kit"), ("o1", "overlay")):
            t = self.root / "trees" / name
            tree = kind != "triage"
            if tree:
                (t / "src/main").mkdir(parents=True)
                (t / "tests").mkdir(parents=True)
                (t / ".kiro").symlink_to(self.root / ".kiro")
            plan = self.root / "worklog/plan" / name
            plan.mkdir(parents=True)
            (plan / "effort.json").write_text(json.dumps({
                "name": name, "kind": kind, "tree": str(t) if tree else None, "repo": repos.get(kind),
                "branch": f"TOY-1/{name}" if tree else None, "base_sha": None}))
            (plan / "status.md").write_text(f"# {name}\n## Stage: IMPLEMENTING\n")
        self.env = git_env(self.dir)
        self.env["EFFORTKIT_INSTANCE"] = str(self.root)

    @property
    def inst(self) -> core.Instance:
        return core.Instance(self.root)

    def plan(self, name):
        return self.root / "worklog/plan" / name

    def tree(self, name):
        return self.root / "trees" / name

    def approve(self, name, text="# Task\n"):
        plan = self.plan(name)
        (plan / "task.md").write_text(text)
        sha = hashlib.sha256((plan / "task.md").read_bytes()).hexdigest()
        (plan / "approval.json").write_text(json.dumps({"task_sha256": sha, "approved_at": "now"}))

    def gate(self, role, tool, tool_input, cwd=None, effort=None, mode="pre"):
        env = dict(self.env)
        if effort:
            env["EFFORTKIT_EFFORT"] = effort
        payload = {"cwd": str(cwd or self.root), "tool_name": tool, "tool_input": tool_input, "session_id": "t"}
        args = [sys.executable, str(GATE), "--instance", str(self.root), mode] + ([role] if role else [])
        p = subprocess.run(args, input=json.dumps(payload), env=env, capture_output=True, text=True)
        return p.returncode, p.stderr + p.stdout

    def cleanup(self):
        subprocess.run(["chmod", "-R", "u+w", str(self.dir)], capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)


class RealInstance:
    """A toy project, a scratch clone of the kit, and an instance installed by the real installer."""

    def __init__(self, answers: dict | None = None):
        self.dir = Path(tempfile.mkdtemp(prefix="ek-real-"))
        self.env = git_env(self.dir)
        src = self.dir / "src"
        src.mkdir()
        (src / "app.py").write_text("print(1)\n")
        (src / "tests").mkdir()
        (src / "tests/test_app.py").write_text("import unittest\n")
        sh("git", "init", "-q", "-b", "main", cwd=src, env=self.env)
        sh("git", "add", "-A", cwd=src, env=self.env)
        sh("git", "commit", "-qm", "TOY-1: first", cwd=src, env=self.env)
        self.remote = self.dir / "toy.git"
        sh("git", "clone", "-q", "--bare", src, self.remote, env=self.env)
        # Kit efforts branch from main of this clone, never from the real kit repository.
        # In a kit tree the clone has no local main, so main is set to the commit under test.
        self.kit_repo = self.dir / "kit"
        sh("git", "clone", "-q", core.KIT, self.kit_repo, env=self.env)
        sh("git", "checkout", "-q", "-B", "main", cwd=self.kit_repo, env=self.env)
        self.env["EFFORTKIT_KIT_REPO"] = str(self.kit_repo)
        self.env["EFFORTKIT_TMUX_SOCKET"] = f"ek-test-{os.getpid()}-{self.dir.name}"
        fake = self.dir / "bin/kiro-cli"
        fake.parent.mkdir()
        fake.write_text('#!/bin/sh\necho "FAKE kiro args: $*"\necho "EFFORTKIT_EFFORT=$EFFORTKIT_EFFORT PWD=$PWD"\n'
                        'echo "PATH0=${PATH%%:*}"\nexit 0\n')
        fake.chmod(0o755)
        self.env["PATH"] = f"{fake.parent}{os.pathsep}{os.environ['PATH']}"
        cfg = core.merge({k: v for k, v in CONFIG.items() if k != "effortkit"}, answers or {})
        cfg["repo"] = {"url": str(self.remote)}
        self.answers = self.dir / "answers.json"
        self.answers.write_text(json.dumps(cfg))
        self.root = self.dir / "inst"
        p = self.kit("install", "--dir", self.root, "--config", self.answers)
        assert p.returncode == 0, p.stderr + p.stdout
        self.env["EFFORTKIT_INSTANCE"] = str(self.root)

    @property
    def inst(self) -> core.Instance:
        return core.Instance(self.root)

    def effort(self, *args, check=False, input=None):
        return sh(sys.executable, EFFORT, *args, env=self.env, check=check, cwd=self.root, input=input)

    def kit(self, *args, check=False):
        return sh(sys.executable, EFFORTKIT, *args, env=self.env, check=check, cwd=self.dir)

    def plan(self, name):
        return self.root / "worklog/plan" / name

    def cleanup(self):
        subprocess.run(["tmux", "-L", self.env["EFFORTKIT_TMUX_SOCKET"], "kill-server"], capture_output=True)
        subprocess.run(["chmod", "-R", "u+w", str(self.dir)], capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)
