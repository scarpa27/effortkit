"""effortkit doctor: what a machine needs before the kit works there, and whether the kit and the instances are sound.

Each check returns (level, name, detail). FAIL stops the workflow, WARN costs a feature, ok is fine.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import core, gen, install, repohooks, skills

# The kiro-cli versions on which the gate behaviour was measured. Another version can change hooks or trust.
MEASURED_KIRO = ("2.33", "2.34")


def run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return None


def version(text: str) -> str:
    m = re.search(r"\d+\.\d+(?:\.\d+)?", text or "")
    return m.group(0) if m else "?"


def at_least(found: str, want: tuple[int, ...]) -> bool:
    try:
        return tuple(int(x) for x in found.split(".")) >= want
    except ValueError:
        return False


def machine() -> list[tuple[str, str, str]]:
    out = []
    py = ".".join(map(str, sys.version_info[:3]))
    out.append(("ok" if sys.version_info >= (3, 9) else "FAIL", "python", f"{py} at {sys.executable} (3.9 or later)"))
    if sys.platform.startswith("linux"):
        out.append(("ok", "platform", "Linux, where the gate behaviour was measured"))
    elif sys.platform == "darwin":
        out.append(("WARN", "platform", "macOS: the process check works, but nobody measured the kiro hooks here"))
    else:
        out.append(("FAIL", "platform", f"{sys.platform}: a kiro hook cannot refuse a call here (kiro issue 8264)"))
    p = run("git", "--version")
    v = version(p.stdout if p else "")
    out.append(("ok" if p and at_least(v, (2, 17)) else "FAIL", "git", f"{v} (2.17 or later)" if p else "missing"))
    p = run("kiro-cli", "--version")
    if not p or p.returncode != 0:
        out.append(("FAIL", "kiro-cli", "missing. Install kiro-cli first"))
    else:
        v = version(p.stdout)
        same = any(v == m or v.startswith(m + ".") for m in MEASURED_KIRO)
        out.append(("ok" if same else "WARN", "kiro-cli", f"{v}" + ("" if same else
                    f". The gate was measured on {' and '.join(m + '.x' for m in MEASURED_KIRO)}: "
                    "run `effortkit selftest` and one stage before you trust it")))
        who = run("kiro-cli", "whoami")
        logged_in = bool(who and who.returncode == 0 and "logged in" in who.stdout.lower())
        out.append(("ok" if logged_in else "FAIL", "kiro-cli login", "logged in" if logged_in else "not logged in. Run kiro-cli login"))
    for tool, why in (("tmux", "detached stages and the improvement round at effort close"),
                      ("rg", "effort find, and the agents search with it"),
                      ("npx", "the lavish skill. Without Node, set skills_off to [\"lavish\"]")):
        out.append(("ok" if shutil.which(tool) else "WARN", tool, ("present" if shutil.which(tool) else "missing") + f": {why}"))
    sign = run("git", "config", "--global", "--get", "commit.gpgsign")
    if sign and sign.stdout.strip().lower() == "true":
        p = subprocess.run(["gpg", "--batch", "--no-tty", "--pinentry-mode", "error", "-s", "-o", "/dev/null"],
                           input=b"x", capture_output=True) if shutil.which("gpg") else None
        ok = bool(p and p.returncode == 0)
        out.append(("ok" if ok else "FAIL", "commit signing", "the gpg agent signs without a terminal" if ok else
                    "gpg needs a passphrase or is missing. Sign once in a terminal, or the agents' commits fail"))
    else:
        out.append(("ok", "commit signing", "not configured"))
    found = shutil.which("effortkit")
    ours = bool(found) and core.real(found) == core.real(core.KIT / "bin/effortkit")
    out.append(("ok" if ours else "WARN", "effortkit on PATH", f"{found}" if ours else
                (f"{found} is another command" if found else "missing") + ". Run `bin/effortkit setup` in the kit"))
    return out


def kit() -> list[tuple[str, str, str]]:
    problems = skills.problems()
    return [("FAIL", "kit skills", p) for p in problems] or [("ok", "kit skills", "every skill matches its lock entry")]


def instance(root: Path) -> list[tuple[str, str, str]]:
    try:
        inst = core.Instance(root)
    except core.InstanceError as exc:
        return [("FAIL", f"instance {root}", str(exc))]
    name = f"instance {inst.name}"
    out = [("FAIL", name, e) for e in install.check_config(inst.root)]
    stale = gen.stale_reason(inst)
    out.append(("WARN" if stale else "ok", f"{name} configs", f"{stale}. Run {inst.bin / 'effort'} gen" if stale else "current"))
    if core.git_common_dir(inst.product) is not None:
        state = repohooks.state(inst, inst.product)
        out.append(("ok" if state == "ok" else "WARN", f"{name} commit-msg hook",
                    state if state == "ok" else f"{state}. Run effortkit install --dir {inst.root} --repair"))
    else:
        out.append(("FAIL", f"{name} project", f"{inst.product} is not a git repository"))
    return out


def report(rows: list[tuple[str, str, str]]) -> int:
    for level, name, detail in rows:
        print(f"{level:4} {name}: {detail}")
    return 1 if any(level == "FAIL" for level, _, _ in rows) else 0


def everything(root: Path | None = None) -> int:
    rows = machine() + kit()
    roots = [root] if root else core.registered_instances()
    for r in roots:
        rows += instance(Path(r))
    if not roots:
        rows.append(("ok", "instances", "none registered yet. Create one with effortkit installer <dir>"))
    return report(rows)
