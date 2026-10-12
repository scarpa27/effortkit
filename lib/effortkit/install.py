"""Create an instance of effortkit for one project, and check the config of an instance.

The installer agent interviews the owner and writes the answers as JSON. install() turns the answers into an
instance. It is deterministic and has no model in it, so it is safe to run again on the same answers.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import core, gen, repohooks

INSTANCE_IGNORE = """# The instance repository tracks instance.json and overlay/. The rest is local state or generated.
/worklog/
/trees/
/locks/
/product.git/
/.kiro/
/bin/
*~
__pycache__/
"""
WORKLOG_IGNORE = """# The worklog: plans, knowledge and workflow reports. Bulk logs of one effort stay out.
/plan/*/scratch/
*~
__pycache__/
"""


class InstallError(Exception):
    pass


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and p.returncode != 0:
        raise InstallError(f"{' '.join(args)} failed: {(p.stderr or p.stdout).strip()[:400]}")
    return p


def placeholder_example(cmd: str) -> str:
    return re.sub(r"<[^>]+>", "x", cmd)


def check_config(root: Path, render: bool = True) -> list[str]:
    """Every problem of the config and the overlay at root, as text. An empty list means the config is usable."""
    errors: list[str] = []
    try:
        inst = core.Instance(root)
    except core.InstanceError as exc:
        return [str(exc)]
    cfg = inst.config
    if not core.NAME_RE.match(inst.name):
        errors.append(f"name {inst.name!r} must be 3 to 50 lowercase letters, digits and '-'")
    if not (cfg["repo"].get("url") or cfg["repo"].get("path")):
        errors.append("repo needs url (a clone source) or path (an existing clone)")
    regexes = [("commit.subject_regex", cfg["commit"].get("subject_regex"))]
    regexes += [("ticket.regex", cfg["ticket"].get("regex"))] if cfg["ticket"].get("regex") else []
    regexes += [(f"tests.patterns[{i}]", p) for i, p in enumerate(cfg["tests"].get("patterns") or [])]
    regexes += [(f"forbidden_commands[{i}].pattern", r.get("pattern")) for i, r in enumerate(cfg.get("forbidden_commands") or [])]
    for where, pattern in regexes:
        try:
            re.compile(pattern or "")
            if not pattern:
                errors.append(f"{where} is empty")
        except re.error as exc:
            errors.append(f"{where} is not a valid regex: {exc}")
    patterns = [p for p in cfg["tests"].get("patterns") or [] if _compiles(p)]
    for cmd in cfg["tests"].get("commands") or []:
        example = placeholder_example(cmd)
        if not any(re.fullmatch(p, example) for p in patterns):
            # The prompts name this command, so a role that may run tests would be refused on it.
            errors.append(f"tests.commands names {cmd!r}, and no tests.patterns entry matches {example!r}")
    for i, r in enumerate(cfg.get("forbidden_commands") or []):
        if not r.get("reason"):
            errors.append(f"forbidden_commands[{i}] needs a reason, so a refusal can explain itself")
    for name, spec in inst.roles.items():
        if spec.get("profile") not in core.PROFILES or spec.get("profile") == "supervisor":
            errors.append(f"role {name}: profile {spec.get('profile')!r} must be one of "
                          f"{', '.join(p for p in core.PROFILES if p != 'supervisor')}")
        if name not in core.BUILTIN_ROLES and not (inst.overlay / "agents" / f"{name}.md").is_file():
            errors.append(f"role {name}: a custom role needs its prompt in overlay/agents/{name}.md")
        if not re.match(r"^[a-z][a-z0-9-]*$", name):
            errors.append(f"role {name}: use lowercase letters, digits and '-'")
    for name, spec in inst.kinds.items():
        if spec.get("repo") not in ("product", "kit", "instance", None):
            errors.append(f"kind {name}: repo must be product, kit, instance or null")
        lane = spec.get("lane")
        if lane and not ((core.KIT / "skills" / lane / "SKILL.md").is_file() or (inst.overlay / "skills" / lane / "SKILL.md").is_file()):
            errors.append(f"kind {name}: lane skill {lane} is in neither {core.KIT / 'skills'} nor overlay/skills")
    for b in inst.push_rules(None).get("protected_branches", []):
        if not repohooks.BRANCH_RE.match(b):
            errors.append(f"push.protected_branches: {b!r} is not a plain branch name")
    if cfg["improve"].get("trigger") not in ("on-close", "manual"):
        errors.append("improve.trigger must be on-close or manual")
    if render and not errors:
        try:
            v = gen.variables(inst)
            for role in [core.SUPERVISOR, *inst.roles]:
                gen.role_prompt(inst, role, v)
                json.dumps(gen.agent_config(inst, role))
            for src in (core.KIT / "steering").glob("*.md"):
                gen.render(src.read_text(encoding="utf-8"), v, str(src))
        except gen.GenError as exc:
            errors.append(str(exc))
    return errors


def _compiles(p: str) -> bool:
    try:
        re.compile(p)
        return True
    except re.error:
        return False


def validate_with_kiro(inst: core.Instance) -> list[str]:
    """kiro-cli agent validate prints an error and can still exit 0, so any output is a failure."""
    if not shutil.which("kiro-cli"):
        return ["kiro-cli is not on PATH, so the agent configs were not validated"]
    out = []
    for f in sorted((inst.kiro / "agents").glob("*.json")):
        p = subprocess.run(["kiro-cli", "agent", "validate", "--path", str(f)], capture_output=True, text=True)
        text = (p.stdout + p.stderr).strip()
        if p.returncode != 0 or text:
            out.append(f"{f.name}: {text or f'exit {p.returncode}'}")
    return out


def project_steering(cfg: dict) -> str:
    tests = cfg["tests"].get("commands") or []
    lines = [f"# {cfg['name']}", "",
             f"- {cfg.get('description') or 'The installer did not record a description yet.'}",
             f"- The repository: `{cfg['repo'].get('url') or cfg['repo'].get('path')}`.",
             f"- The default base of a new effort: `{cfg['repo'].get('default_base')}`.",
             f"- A commit subject looks like `{cfg['commit']['subject_help']}`."]
    lines += [f"- Run the tests with `{t}`." for t in tests] or ["- No test command is configured yet."]
    return "\n".join(lines) + "\n"


def commit_all(repo: Path, message: str, sign: bool) -> None:
    run("git", "add", "-A", cwd=repo)
    if run("git", "diff", "--cached", "--quiet", cwd=repo, check=False).returncode == 0:
        return
    args = ["git"] + ([] if sign else ["-c", "commit.gpgsign=false"]) + ["commit", "-q", "-m", message]
    p = run(*args, cwd=repo, check=False)
    if p.returncode != 0 and sign:
        # A gpg agent without a cached key cannot sign here. The scaffold commit is not worth a failed install.
        run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, cwd=repo)
    elif p.returncode != 0:
        raise InstallError(f"git commit in {repo} failed: {(p.stderr or p.stdout).strip()[:300]}")


def install(target: Path, answers: dict, clone: bool = True, log=print) -> core.Instance:
    target = core.real(target)
    if (target / core.INSTANCE_FILE).exists():
        raise InstallError(f"{target} holds an instance already. Change it in an overlay effort, "
                           "or run `effortkit install --repair` to restore its layout.")
    if target.exists() and any(p.name not in (".install-gate.log",) for p in target.iterdir()):
        raise InstallError(f"{target} exists and is not empty. Choose a new folder.")
    cfg = core.merge({"effortkit": core.SCHEMA}, answers)
    cfg["effortkit"] = core.SCHEMA
    cfg.setdefault("name", target.name)
    if not core.NAME_RE.match(cfg["name"]):
        raise InstallError(f"name {cfg['name']!r} must be 3 to 50 lowercase letters, digits and '-'")
    repo = cfg.setdefault("repo", {})
    if not (repo.get("url") or repo.get("path")):
        raise InstallError("the answers need repo.url (a clone source) or repo.path (an existing clone)")
    target.mkdir(parents=True, exist_ok=True)
    for d in ("worklog/plan", "worklog/knowledge/inbox", "worklog/improvements/inbox", "worklog/improvements/done",
              "worklog/reference", "trees", "locks", "overlay/steering", "overlay/agents", "overlay/skills", "bin"):
        (target / d).mkdir(parents=True, exist_ok=True)
    product = target / "product.git"
    if repo.get("path"):
        src = core.real(repo["path"])
        if core.git_common_dir(src) is None:
            raise InstallError(f"repo.path {src} is not a git repository")
        repo["path"] = str(src)
        log(f"using the existing clone {src}. Efforts add worktrees to it.")
    elif clone:
        log(f"cloning {repo['url']} into {product} (bare) ...")
        run("git", "clone", "-q", "--bare", repo["url"], str(product))
        remote = repo.get("remote") or "origin"
        if remote != "origin":
            run("git", "remote", "rename", "origin", remote, cwd=product)
        # A bare clone maps the remote branches onto local branches. Efforts need remote-tracking refs instead.
        run("git", "config", f"remote.{remote}.fetch", f"+refs/heads/*:refs/remotes/{remote}/*", cwd=product)
        run("git", "fetch", "-q", remote, cwd=product)
    if not repo.get("default_base"):
        remote = repo.get("remote") or "origin"
        if repo.get("path"):
            src = core.real(repo["path"])
            tracked = run("git", "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD", cwd=src, check=False).stdout.strip()
            repo["default_base"] = tracked or run("git", "symbolic-ref", "--short", "HEAD", cwd=src, check=False).stdout.strip() or "main"
        else:
            head = run("git", "symbolic-ref", "--short", "HEAD", cwd=product, check=False).stdout.strip() or "main"
            repo["default_base"] = f"{remote}/{head}"
        log(f"default base: {repo['default_base']}")
    (target / core.INSTANCE_FILE).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    errors = check_config(target, render=False)
    if errors:
        raise InstallError("the config has problems:\n  " + "\n  ".join(errors))
    inst = core.Instance(target)
    if not (inst.overlay / "steering/project.md").exists():
        (inst.overlay / "steering/project.md").write_text(project_steering(inst.config), encoding="utf-8")
    for keep in ("agents", "skills"):
        (inst.overlay / keep / ".gitkeep").touch()
    (inst.knowledge / "project.md").exists() or (inst.knowledge / "project.md").write_text(
        f"# {inst.name}: facts that the efforts learned\n", encoding="utf-8")
    errors = check_config(target)
    if errors:
        raise InstallError("the config has problems:\n  " + "\n  ".join(errors))
    (target / ".gitignore").write_text(INSTANCE_IGNORE, encoding="utf-8")
    (inst.worklog / ".gitignore").write_text(WORKLOG_IGNORE, encoding="utf-8")
    sign = run("git", "config", "--get", "commit.gpgsign", check=False).stdout.strip().lower() == "true"
    for repo_dir, message in ((target, "effortkit: new instance"), (inst.worklog, "effort: new worklog")):
        if not (repo_dir / ".git").exists():
            run("git", "init", "-q", "-b", "main", cwd=repo_dir)
        commit_all(repo_dir, message, sign and repo_dir == target)
    for r in {inst.product, inst.root}:
        if core.git_common_dir(r) is not None:
            changed = repohooks.install(inst, r)
            if changed:
                log(f"installed the {', '.join(changed)} hooks in {r}")
    gen.generate(inst)
    core.register_instance(inst.root)
    return inst


def repair(target: Path, log=print) -> core.Instance:
    """Restore the layout, the hooks and the generated files of an existing instance. The config stays."""
    inst = core.Instance(target)
    for d in (inst.plan, inst.inbox, inst.reports, inst.reports_done, inst.reference, inst.trees, inst.locks,
              inst.overlay / "steering", inst.overlay / "agents", inst.overlay / "skills", inst.bin):
        d.mkdir(parents=True, exist_ok=True)
    for r in {inst.product, inst.root}:
        if core.git_common_dir(r) is not None:
            changed = repohooks.install(inst, r)
            if changed:
                log(f"installed the {', '.join(changed)} hooks in {r}")
    errors = check_config(inst.root)
    if errors:
        raise InstallError("the config has problems:\n  " + "\n  ".join(errors))
    gen.generate(inst)
    core.register_instance(inst.root)
    return inst
