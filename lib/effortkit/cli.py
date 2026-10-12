"""effort - start, run and track the efforts of one effortkit instance.

  effort new <name> --kind <kind> [--base <ref>] [--ticket <key>] [--branch <b>] [--no-setup]
      --branch on a branch that exists continues it: its tip is the base, and --base is ignored.
  effort start <name> [--terse] [--resume]      a supervisor session for one effort
  effort home [--terse] [--resume]              the owner's home supervisor session
  effort run <name> --role <role> --brief <file> [--detach] [--minutes N] [--model M]
  effort wait <run-id> [--timeout S]            effort logs <run-id> [--tail N]
  effort attach <name>                          watch the detached runs of an effort
  effort status [--collisions] [--all]
  effort approve <name> [--revoke] [--force]    the owner only, in a terminal
  effort close <name> [--force]
  effort find <word>...                         effort kb add <topic> <text>
  effort report <text> [--scope kit|overlay|unsure] [--area A] [--severity S]   a workflow report
  effort improve [--scope auto|kit|overlay] [--detach] [--no-run]   effort improve stats
  effort preflight <name> [--fix]   effort plan-review <name> [decision.md]   effort gen [--check]   effort snapshot

The instance is --instance <dir>, else EFFORTKIT_INSTANCE, else the nearest parent folder with instance.json.
"""
from __future__ import annotations

import argparse
import calendar
import fcntl
import getpass
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import core, gen, improve, repohooks

SELF = core.KIT / "bin/effort"
INST: core.Instance


def die(msg: str, code: int = 2) -> None:
    print(f"effort: {msg}", file=sys.stderr)
    sys.exit(code)


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and p.returncode != 0:
        die(f"git {' '.join(args)} failed: {(p.stderr or p.stdout).strip()[:400]}")
    return p.stdout.strip()


def require_effort(name: str, allow_closed: bool = False) -> core.Effort:
    e = INST.load_effort(name)
    if e is None:
        die(f"no effort named '{name}'. `effort status` lists them.")
    if e.closed and not allow_closed:
        die(f"effort '{name}' is closed.")
    return e


def snapshot(message: str) -> None:
    """Commit the worklog. One lock serialises commits, because several effort commands can run at once."""
    if not (INST.worklog / ".git").exists():
        return
    INST.locks.mkdir(parents=True, exist_ok=True)
    with open(INST.locks / "worklog.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        git("add", "-A", cwd=INST.worklog)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=INST.worklog).returncode == 0:
            return
        # Bookkeeping of the effort command, never pushed to a shared remote, so a missing gpg agent must not stop it.
        p = subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m",
                            f"effort: {message}"], cwd=INST.worklog, capture_output=True, text=True)
        if p.returncode != 0:
            print(f"effort: warning: the worklog commit failed: {(p.stderr or p.stdout).strip()[:200]}", file=sys.stderr)


def initial_status(name: str, kind: str, ticket: str | None) -> str:
    stage = INST.kinds.get(kind, {}).get("stage", "EXPLORING")
    return (f"# {name}\n## Stage: {stage}\n## Ticket: {ticket or 'none'}\n## Last Activity: {core.now_utc()}. "
            f"`effort new` created the effort.\n## Current Wave: none\n## Blockers: none\n## Notes:\n")


def ensure_excludes(tree: Path) -> None:
    """All worktrees share one info/exclude. Without the .kiro line, the link alone makes every tree dirty."""
    common = Path(git("rev-parse", "--git-common-dir", cwd=tree))
    exclude = (common if common.is_absolute() else tree / common) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    have = exclude.read_text().splitlines() if exclude.exists() else []
    missing = [l for l in ["/.kiro", *INST.config["tree_excludes"]] if l not in have]
    if missing:
        with open(exclude, "a") as f:
            f.write("\n".join(["# Added by the effortkit effort command."] + missing) + "\n")


def provision(e: core.Effort, no_setup: bool) -> None:
    tree = e.tree
    ensure_excludes(tree)
    link = tree / ".kiro"
    if not link.is_symlink() and not link.exists():
        link.symlink_to(INST.kiro)
    if no_setup or INST.kinds.get(e.kind, {}).get("repo") != "product":
        return
    steps = INST.config.get("tree_setup") or []
    if not steps:
        return
    log = e.plan / "scratch" / "setup.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"effort: running {len(steps)} tree setup commands. Log: {log}", file=sys.stderr)
    with open(log, "w") as f:
        for step in steps:
            f.write(f"$ {step}\n")
            f.flush()
            code = subprocess.run(step, shell=True, cwd=tree, stdout=f, stderr=subprocess.STDOUT).returncode
            if code != 0:
                print(f"effort: warning: the setup command failed with exit {code}: {step}. See {log}", file=sys.stderr)
                return


def default_branch(kind: str, name: str, ticket: str | None) -> str:
    spec = INST.kinds.get(kind, {})
    if spec.get("repo") in ("kit", "instance"):
        return f"workflow/{name}"
    b = INST.config["branch"]
    return (b["template"] if ticket else b["fallback"]).format(ticket=ticket or "", name=name)


def create_effort(name: str, kind: str, base: str | None, ticket: str | None, branch: str | None,
                  no_setup: bool) -> core.Effort:
    if not core.NAME_RE.match(name):
        die(f"'{name}' is not a valid effort name. Use 3 to 50 lowercase letters, digits and '-'.")
    if (INST.plan / name).exists():
        die(f"effort '{name}' exists already.")
    kinds = INST.kinds
    if kind not in kinds:
        die(f"unknown kind '{kind}'. Kinds: {', '.join(kinds)}")
    regex = INST.config["ticket"].get("regex")
    if ticket and regex and not re.match(regex, ticket):
        die(f"--ticket must match {regex}, for example {INST.config['ticket'].get('example') or 'ABC-123'}.")
    spec = kinds[kind]
    repo = INST.repo_for(kind)
    open_trees = [e for e in INST.efforts() if e.tree]
    if repo and len(open_trees) >= INST.config["max_efforts"]:
        die(f"{len(open_trees)} efforts with a tree are open. The limit is {INST.config['max_efforts']}. Close one first.")
    data = {"name": name, "kind": kind, "ticket": ticket, "created": core.now_utc(), "tree": None, "repo": None,
            "branch": None, "base_ref": None, "base_sha": None}
    if repo:
        if not (repo / "HEAD").exists() and not (repo / ".git").exists():
            die(f"the repository of kind {kind} is missing: {repo}")
        base = base or spec.get("base") or INST.config["repo"].get("default_base")
        # A named branch that exists already is a continuation: the effort starts where the last one stopped, so its
        # tip is the base. Only an explicit --branch continues; a default name that collides is an accident.
        cont = bool(branch) and not spec.get("detached") and bool(
            git("show-ref", "--verify", f"refs/heads/{branch}", cwd=repo, check=False))
        if not base and not cont:
            die(f"kind {kind} needs --base, for example --base origin/main. A wrong base is invisible later.")
        for hook in repohooks.install(INST, repo):
            print(f"effort: installed the {hook} hook in {repo}", file=sys.stderr)
        if spec.get("repo") == "product":
            remote = INST.config["repo"].get("remote", "origin")
            if git("remote", cwd=repo, check=False) and subprocess.run(
                    ["git", "fetch", "-q", remote], cwd=repo, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                    capture_output=True, timeout=300).returncode != 0:
                print(f"effort: warning: git fetch {remote} failed. The base uses the local refs.", file=sys.stderr)
        tree = INST.trees / name
        INST.trees.mkdir(parents=True, exist_ok=True)
        if cont:
            used = next((e.name for e in INST.efforts() if e.tree and e.data.get("branch") == branch), None)
            if used:
                die(f"effort '{used}' works on branch {branch}. One tree per branch: close it first.")
            base_sha = git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=repo)
            base = branch
            git("worktree", "add", "-q", str(tree), branch, cwd=repo)
        else:
            base_sha = git("rev-parse", "--verify", f"{base}^{{commit}}", cwd=repo)
            if spec.get("detached"):
                git("worktree", "add", "-q", "--detach", str(tree), base_sha, cwd=repo)
                branch = None
            else:
                branch = branch or default_branch(kind, name, ticket)
                if git("show-ref", "--verify", f"refs/heads/{branch}", cwd=repo, check=False):
                    die(f"branch {branch} exists already. Name it with --branch to continue it, or name another one.")
                git("worktree", "add", "-q", "-b", branch, str(tree), base_sha, cwd=repo)
        data.update(tree=str(tree), repo=str(repo), branch=branch, base_ref=base, base_sha=base_sha)
    plan = INST.plan / name
    for sub in ("findings", "briefs"):
        (plan / sub).mkdir(parents=True, exist_ok=True)
    core.write_json_once(plan / "effort.json", data)
    (plan / "status.md").write_text(initial_status(name, kind, ticket), encoding="utf-8")
    e = core.Effort(INST, name, data)
    if e.tree:
        provision(e, no_setup)
    return e


# ---------------------------------------------------------------- preflight and sessions

def signing_needed(cwd: Path) -> bool:
    return git("config", "--get", "commit.gpgsign", cwd=cwd, check=False).lower() == "true"


def preflight(e: core.Effort, full: bool = True) -> list[tuple[str, bool, str]]:
    res: list[tuple[str, bool, str]] = []
    if e.tree:
        agent = e.tree / ".kiro/agents/supervisor.json"
        res.append(("agent link", agent.is_file() and core.within(core.real(agent), core.real(INST.kiro)),
                    f"{e.tree}/.kiro -> {INST.kiro}"))
        if full:
            dirty = git("status", "--porcelain", cwd=e.tree, check=False)
            res.append(("clean tree", not dirty, f"{len(dirty.splitlines())} changed paths" if dirty else "clean"))
            head = git("rev-parse", "--abbrev-ref", "HEAD", cwd=e.tree, check=False)
            want = e.data.get("branch") or "HEAD"
            res.append(("branch", head == want, f"on {head}, want {want}"))
    if full and e.repo:
        state = repohooks.state(INST, e.repo)
        res.append(("commit-msg hook", state == "ok", f"{e.repo} hook is {state}"
                    + (f". Install it: effort preflight {e.name} --fix" if state != "ok" else "")))
        if e.tree and signing_needed(e.tree):
            key = git("config", "--get", "user.signingkey", cwd=e.tree, check=False)
            p = subprocess.run(["gpg", "--batch", "--no-tty", "--pinentry-mode", "error", "-s", "-o", "/dev/null"]
                               + (["-u", key] if key else []), input=b"x", capture_output=True)
            res.append(("signing without a terminal", p.returncode == 0, "gpg agent has the key" if p.returncode == 0 else
                        "gpg needs a passphrase. Sign once in a terminal, or the agents' commits fail."))
    stale = gen.stale_reason(INST)
    res.append(("generated configs", not stale, stale or "current"))
    return res


def ensure_generated() -> None:
    reason = gen.stale_reason(INST)
    if reason:
        print(f"effort: regenerating the agent configs: {reason}", file=sys.stderr)
        try:
            gen.generate(INST)
        except gen.GenError as exc:
            die(f"effort gen failed: {exc}")


def quick_check(e: core.Effort) -> None:
    if e.tree and not e.tree.is_dir():
        die(f"the tree of '{e.name}' is missing: {e.tree}")
    ensure_generated()
    bad = [r for r in preflight(e, full=False) if not r[1]]
    if bad:
        die(f"preflight failed for '{e.name}': " + "; ".join(f"{n}: {d}" for n, _, d in bad)
            + ". Without the link, kiro-cli would run its default agent with no hooks.")


def session_env(e: core.Effort | None, terse: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("EFFORTKIT_EFFORT", "EFFORTKIT_TERSE", "EFFORTKIT_GATE_DEBUG")}
    env["EFFORTKIT_INSTANCE"] = str(INST.root)
    if e:
        env["EFFORTKIT_EFFORT"] = e.name
    if terse:
        env["EFFORTKIT_TERSE"] = "1"
    env["LAVISH_AXI_TELEMETRY"] = "0"
    # The agents and the owner's ! shell call `effort` by name, so this instance's command comes first on PATH.
    env["PATH"] = f"{INST.bin}{os.pathsep}{env.get('PATH', '')}"
    host = INST.config["forge"].get("host")
    if host:
        env.setdefault("GITLAB_HOST", host)
        env.setdefault("GH_HOST", host)
    return env


def exec_session(e: core.Effort | None, terse: bool, resume: bool) -> None:
    lock = INST.locks / f"{e.name if e else 'home'}.session"
    pid = INST.live_session(e.name if e else "home")
    if pid and e:
        die(f"effort '{e.name}' already has a live supervisor session (pid {pid}). One supervisor per effort.")
    if pid:
        print(f"effort: note: another home session is live (pid {pid}).", file=sys.stderr)
    ensure_generated()
    cwd = e.tree if e and e.tree else INST.root
    INST.locks.mkdir(parents=True, exist_ok=True)
    core.write_json_once(lock, {"pid": os.getpid(), "started": core.now_utc(), "cwd": str(cwd)})
    os.chdir(cwd)
    argv = ["kiro-cli", "chat", "--agent", core.SUPERVISOR] + (["--resume"] if resume else [])
    os.execvpe("kiro-cli", argv, session_env(e, terse))


def cmd_start(a) -> None:
    e = require_effort(a.name)
    quick_check(e)
    exec_session(e, a.terse, a.resume)


def cmd_home(a) -> None:
    exec_session(None, a.terse, a.resume)


# ---------------------------------------------------------------- runs

def find_run(run_id: str) -> tuple[core.Effort, dict]:
    for e in INST.efforts(include_closed=True):
        rec = core.read_json(core.runs_dir(e) / f"{run_id}.json")
        if rec:
            return e, rec
    die(f"no run named '{run_id}'. `effort status` lists the runs.")


def execute(e: core.Effort, rec: dict, tee: bool) -> int:
    log = core.run_log(e, rec["id"])
    log.parent.mkdir(parents=True, exist_ok=True)
    log.with_suffix(".pid").write_text(str(os.getpid()))
    prompt = Path(rec["brief"]).read_text(encoding="utf-8")
    argv = ["kiro-cli", "chat", "--agent", rec["role"], "--no-interactive"]
    argv += (["--model", rec["model"]] if rec.get("model") else []) + [prompt]
    proc = subprocess.Popen(argv, cwd=rec["cwd"], env=session_env(e, False), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    timed_out, done = threading.Event(), threading.Event()

    def watchdog() -> None:
        if not done.wait(rec["minutes"] * 60):
            timed_out.set()
            try:
                os.killpg(proc.pid, 15)
            except OSError:
                pass
    threading.Thread(target=watchdog, daemon=True).start()
    with open(log, "wb") as f:
        for chunk in iter(lambda: proc.stdout.readline(), b""):
            f.write(chunk)
            f.flush()
            if tee:
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
    code = proc.wait()
    done.set()
    code = 124 if timed_out.is_set() else code
    (core.runs_dir(e) / f"{rec['id']}.exit").write_text(f"{code}\n")
    return code


def start_run(e: core.Effort, role: str, brief: Path, detach: bool, minutes: int, model: str | None) -> str:
    run_id = f"{core.stamp()}-{role}-{os.urandom(2).hex()}"
    rec = {"id": run_id, "effort": e.name, "role": role, "brief": str(brief), "cwd": str(e.tree or INST.root),
           "created": core.now_utc(), "minutes": minutes, "model": model, "detached": detach}
    core.write_json_once(core.runs_dir(e) / f"{run_id}.json", rec)
    if not detach:
        sys.exit(execute(e, rec, tee=True))
    cmd = shlex.join([sys.executable, str(SELF), "--instance", str(INST.root), "_exec", e.name, run_id])
    tm = ["tmux", "-L", tmux_socket()]
    window = f"{role}-{run_id[9:15]}"
    exists = subprocess.run(tm + ["has-session", "-t", e.name], capture_output=True).returncode == 0
    args = (["new-window", "-d", "-t", e.name, "-n", window, cmd] if exists
            else ["new-session", "-d", "-s", e.name, "-n", window, cmd])
    try:
        p = subprocess.run(tm + args, capture_output=True, text=True)
    except FileNotFoundError:
        die("tmux is missing, so --detach cannot work. Run the stage without --detach.")
    if p.returncode != 0:
        die(f"tmux failed: {p.stderr.strip()}")
    return run_id


def tmux_socket() -> str:
    return os.environ.get("EFFORTKIT_TMUX_SOCKET") or f"effortkit-{INST.name}"


def cmd_run(a) -> None:
    e = require_effort(a.name)
    quick_check(e)
    if a.role == core.SUPERVISOR:
        die("effort run starts specialists. Use `effort start` for a supervisor session.")
    if a.role not in INST.roles or not (INST.kiro / "agents" / f"{a.role}.json").is_file():
        die(f"no role named '{a.role}'. Roles: {', '.join(INST.roles)}")
    brief = Path(a.brief).resolve()
    if not brief.is_file():
        die(f"no brief file at {brief}. Write the brief into {e.plan / 'briefs'} first.")
    run_id = start_run(e, a.role, brief, a.detach, a.minutes, a.model)
    print(f"run {run_id} started in tmux window {e.name} (socket {tmux_socket()})")
    print(f"  wait:   effort wait {run_id}")
    print(f"  watch:  effort attach {e.name}")


def cmd_exec(a) -> None:
    e = require_effort(a.name, allow_closed=True)
    rec = core.read_json(core.runs_dir(e) / f"{a.run_id}.json")
    if not rec:
        die(f"no run record {a.run_id}")
    sys.exit(execute(e, rec, tee=False))


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s)


def cmd_wait(a) -> None:
    e, rec = find_run(a.run_id)
    start = time.time()
    created = calendar.timegm(time.strptime(rec["created"], "%Y-%m-%dT%H:%M:%SZ"))
    while True:
        state, code = core.run_state(e, rec["id"])
        if state == "done" or (state == "lost" and time.time() - created > 20):
            break
        if a.timeout and time.time() - start > a.timeout:
            print(f"run {rec['id']} is still running after {a.timeout} s.")
            sys.exit(3)
        time.sleep(3)
    log = core.run_log(e, rec["id"])
    tail = strip_ansi(log.read_text(errors="replace")).splitlines()[-a.tail:] if log.exists() else []
    print("\n".join(tail))
    print(f"--- run {rec['id']} ({rec['role']}, effort {e.name}): {state}, exit {code}. Log: {log}")
    sys.exit(0 if code == 0 else 1)


def cmd_logs(a) -> None:
    e, rec = find_run(a.run_id)
    log = core.run_log(e, rec["id"])
    if not log.exists():
        die(f"no log yet: {log}")
    print("\n".join(strip_ansi(log.read_text(errors="replace")).splitlines()[-a.tail:]))


def cmd_attach(a) -> None:
    require_effort(a.name)
    os.execvp("tmux", ["tmux", "-L", tmux_socket(), "attach", "-t", a.name])


# ---------------------------------------------------------------- lifecycle

def cmd_new(a) -> None:
    e = create_effort(a.name, a.kind, a.base, a.ticket, a.branch, a.no_setup)
    print(f"effort {e.name} ({e.kind}) created")
    print(f"  plan folder  {e.plan}")
    if e.tree:
        print(f"  tree         {e.tree}")
        print(f"  branch       {e.data.get('branch') or 'detached'} at {e.data['base_sha'][:12]} ({e.data['base_ref']})")
    ensure_generated()
    bad = []
    for name, ok, detail in preflight(e):
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {detail}")
        bad += [] if ok else [name]
    snapshot(f"new {e.name} ({e.kind})")
    if bad:
        print(f"effort: preflight failed: {', '.join(bad)}. Fix it, then run `effort preflight {e.name}`.", file=sys.stderr)
        sys.exit(1)


def cmd_preflight(a) -> None:
    e = require_effort(a.name)
    if a.fix:
        if e.repo:
            for hook in repohooks.install(INST, e.repo):
                print(f"installed the {hook} hook in {e.repo}")
        if gen.stale_reason(INST):
            gen.generate(INST)
            print("regenerated the agent configs")
    res = preflight(e)
    for name, ok, detail in res:
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")
    sys.exit(0 if all(ok for _, ok, _ in res) else 1)


def changed_files(e: core.Effort) -> set[str]:
    if not (e.tree and e.tree.is_dir() and e.data.get("base_sha")):
        return set()
    out = git("diff", "--name-only", e.data["base_sha"], cwd=e.tree, check=False).splitlines()
    out += git("ls-files", "--others", "--exclude-standard", cwd=e.tree, check=False).splitlines()
    return {f for f in out if f}


def cmd_status(a) -> None:
    efforts = INST.efforts(include_closed=a.all)
    if not efforts:
        print(f"no efforts in {INST.name}. Create one with: effort new <name> --kind <kind> --base <ref>")
    else:
        print(f"{'effort':30} {'kind':8} {'stage':18} {'approval':9} {'session':8} {'runs':12} branch")
    live_runs = []
    for e in efforts:
        runs = core.list_runs(e)
        states = [core.run_state(e, r["id"]) for r in runs]
        live = [r for r, (s, _) in zip(runs, states) if s == "live"]
        live_runs += [(e, r) for r in live]
        session = "live" if INST.live_session(e.name) else "-"
        stage = "CLOSED" if e.closed else e.stage()
        print(f"{e.name:30} {e.kind:8} {stage:18} {e.approval()[0]:9} {session:8} "
              f"{f'{len(live)} live/{len(runs)}':12} {e.data.get('branch') or '-'}")
    for e, r in live_runs:
        print(f"  live run {r['id']} ({r['role']}, {e.name}) since {r['created']}")
    pending = improve.pending_reports(INST)
    if pending:
        print(f"workflow reports: {len(pending)} open. `effort improve` starts a round, `effort improve stats` shows the trend.")
    if a.collisions:
        product = [e for e in efforts if e.tree and e.data.get("repo") == str(INST.product) and not e.closed]
        files = {e.name: changed_files(e) for e in product}
        hits = False
        for i, x in enumerate(product):
            for y in product[i + 1:]:
                both = sorted(files[x.name] & files[y.name])
                if both:
                    hits = True
                    print(f"collision {x.name} <-> {y.name}: {', '.join(both[:10])}{' ...' if len(both) > 10 else ''}")
        if not hits:
            print("no collisions: no two open efforts change the same file.")


def cmd_approve(a) -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        die("effort approve needs a terminal, because only the owner approves. In the chat, type: !effort approve <name>")
    e = require_effort(a.name)
    rec_path = e.plan / "approval.json"
    if a.revoke:
        rec_path.unlink(missing_ok=True)
        snapshot(f"revoke approval of {e.name}")
        print(f"approval of {e.name} revoked")
        return
    task = e.plan / "task.md"
    sha = core.sha256_file(task)
    if sha is None:
        die(f"{task} does not exist. The planner writes it first.")
    questions = e.plan / "questions.md"
    if questions.exists() and questions.read_text(encoding="utf-8").strip() != "NO_QUESTIONS" \
            and not (e.plan / "answers.md").exists() and not a.force:
        die(f"{questions} has open questions and there is no answers.md. Answer them first, or use --force.")
    title = next((l for l in task.read_text(encoding="utf-8").splitlines() if l.startswith("#")), "(no title)")
    core.write_json_once(rec_path, {"effort": e.name, "task_sha256": sha, "approved_at": core.now_utc(),
                                    "approved_by": getpass.getuser(), "tty": os.ttyname(0)})
    snapshot(f"approve {e.name} task {sha[:12]}")
    print(f"approved {e.name}: {title}")
    print(f"  task.md sha256 {sha[:12]}. A change to task.md needs a new approval.")


def is_round(e: core.Effort) -> bool:
    return INST.kinds.get(e.kind, {}).get("repo") in ("kit", "instance")


def cmd_close(a) -> None:
    e = require_effort(a.name)
    if INST.live_session(e.name):
        die(f"effort {e.name} has a live supervisor session. End it first.")
    live = [r["id"] for r in core.list_runs(e) if core.run_state(e, r["id"])[0] == "live"]
    if live:
        die(f"effort {e.name} has live runs: {', '.join(live)}")
    pending = [p.name for p in INST.inbox.glob(f"*-{e.name}-*.md")] if INST.inbox.is_dir() else []
    if pending and not a.force:
        die(f"merge the knowledge inbox entries of {e.name} into the topic files first: {', '.join(pending)}. Or use --force.")
    head = None
    if e.tree and e.tree.is_dir():
        if git("status", "--porcelain", cwd=e.tree, check=False) and not a.force:
            die(f"the tree of {e.name} has uncommitted changes. Commit them, or use --force.")
        head = git("rev-parse", "HEAD", cwd=e.tree, check=False)
        if e.data.get("branch"):
            against = ["--not", "main"] if is_round(e) else ["--not", "--remotes"]
            unpushed = git("rev-list", "HEAD", *against, cwd=e.tree, check=False)
            if unpushed and not a.force:
                n = len(unpushed.splitlines())
                where = "not in main" if is_round(e) else "on no remote branch"
                die(f"{n} commits of {e.name} are {where}. {'Merge' if is_round(e) else 'Push'} them first, "
                    "or use --force. The branch stays after close.")
        git("worktree", "remove", *(["--force"] if a.force else []), str(e.tree), cwd=e.repo)
    settled = improve.settle(INST, e) if is_round(e) else []
    core.write_json_once(e.plan / "closed.json", {"closed_at": core.now_utc(), "head": head, "branch": e.data.get("branch")})
    snapshot(f"close {e.name}")
    print(f"effort {e.name} closed{'. Its branch ' + e.data['branch'] + ' stays.' if e.data.get('branch') else '.'}")
    for line in settled:
        print(f"  report {line}")
    if not is_round(e):
        maybe_start_round()


def maybe_start_round() -> None:
    """The improvement round that the config asks for at the end of an effort."""
    cfg = INST.config["improve"]
    pending = improve.pending_reports(INST)
    threshold = int(cfg.get("threshold", 3))
    if not pending:
        return
    open_rounds = [x.name for x in INST.efforts() if is_round(x) and x.name.startswith("improve-")]
    if cfg.get("trigger") != "on-close" or len(pending) < threshold:
        print(f"workflow reports: {len(pending)} open (threshold {threshold}). `effort improve` starts a round.")
        return
    if open_rounds:
        print(f"workflow reports: {len(pending)} open. Round {', '.join(open_rounds)} is still open, so no new round starts.")
        return
    print(f"workflow reports: {len(pending)} open, threshold {threshold}. Starting an improvement round in the background.")
    p = subprocess.run([sys.executable, str(SELF), "--instance", str(INST.root), "improve", "--detach"],
                       capture_output=True, text=True)
    print((p.stdout + p.stderr).strip())


# ---------------------------------------------------------------- knowledge, reports and search

def cmd_find(a) -> None:
    root = INST.plan
    if not root.is_dir():
        return
    folders = None
    for word in a.words:
        p = subprocess.run(["rg", "-l", "-i", "-u", "-F", "--max-filesize", "2M", "-g", "!scratch/**", word, str(root)],
                           capture_output=True, text=True)
        hit = {Path(f).relative_to(root).parts[0] for f in p.stdout.splitlines() if f}
        folders = hit if folders is None else folders & hit
    for name in sorted(folders or []):
        e = INST.load_effort(name)
        stage = e.stage() if e else "?"
        when = time.strftime("%Y-%m-%d", time.localtime((root / name).stat().st_mtime))
        print(f"{when}  {stage:18} {root / name}")


def cmd_kb(a) -> None:
    if a.action != "add":
        die("usage: effort kb add <topic> <text> [--effort E] [--role R]")
    topic = a.topic.removesuffix(".md")
    if not (INST.knowledge / f"{topic}.md").exists() and topic != "new":
        names = ", ".join(sorted(p.stem for p in INST.knowledge.glob("*.md"))) or "none yet"
        die(f"no knowledge topic '{topic}'. Topics: {names}, or 'new' for a new topic.")
    effort = a.effort or os.environ.get("EFFORTKIT_EFFORT") or "home"
    INST.inbox.mkdir(parents=True, exist_ok=True)
    path = INST.inbox / f"{core.stamp()}-{effort}-{a.role}.md"
    path.write_text(f"target: {topic}.md\n\n{' '.join(a.text).strip()}\n", encoding="utf-8")
    print(path)


def cmd_report(a) -> None:
    effort = a.effort or os.environ.get("EFFORTKIT_EFFORT") or "home"
    path = improve.write_report(INST, " ".join(a.text), a.scope, a.area, a.severity, effort, a.role)
    print(path)


def round_brief(e: core.Effort, reports: list[improve.Report], since: str) -> Path:
    layer = "the kit" if e.kind == "kit" else "the overlay of this instance"
    lines = [f"# Improvement round {e.name}", "",
             f"Triage the workflow reports below and plan the fixes to {layer}.",
             f"The effort's tree `{e.tree}` is a checkout of that layer, on branch `{e.data.get('branch')}`.",
             f"Plan folder: `{e.plan}`. Write `triage.md`, `task.md` and `questions.md` there.",
             f"Signals of the gates and the runs since {since or 'the start'}: `{e.plan / 'signals.md'}`.",
             f"Earlier decisions: `{INST.ledger}`.", "", "## Reports"]
    lines += [f"- `{r.path}` ({r.severity}, area {r.area}, from {r.effort or '?'} {r.role or ''})".rstrip() for r in reports]
    if not reports:
        lines.append("- none. Work from the signals alone.")
    lines += ["", "## Out of scope",
              "- Changes to the other layer. Correct the scope line of such a report and decide `deferred`.",
              "- Implementation. The developer implements after the owner approves `task.md`."]
    brief = e.plan / "briefs" / f"{core.stamp()}-improver.md"
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return brief


def cmd_improve(a) -> None:
    if a.action == "stats":
        print(improve.stats(INST))
        return
    if a.action:
        die(f"unknown improve action '{a.action}'. Use `effort improve` or `effort improve stats`.")
    pending = improve.pending_reports(INST)
    st = improve.state(INST)
    since = st.get("signals_until", "")
    sig = improve.signals(INST, since)
    by_scope = {"kit": [r for r in pending if r.scope in ("kit", "unsure")],
                "overlay": [r for r in pending if r.scope == "overlay"]}
    if a.scope == "auto":
        scopes = [s for s in ("kit", "overlay") if by_scope[s]]
        if not scopes and (sig["refusals"] or sig["failed_runs"]):
            scopes = ["kit"]
    else:
        scopes = [a.scope]
    if not scopes:
        print("nothing to improve: no open workflow reports and no new signals.")
        return
    started = []
    for scope in scopes:
        name = f"improve-{scope}-{time.strftime('%Y%m%d-%H%M%S')}"
        e = create_effort(name, scope, None, None, None, no_setup=True)
        (e.plan / "signals.md").write_text(improve.signals_markdown(sig), encoding="utf-8")
        brief = round_brief(e, by_scope[scope], since)
        print(f"improvement round {name}: {len(by_scope[scope])} reports, {len(sig['refusals'])} refusal patterns")
        print(f"  plan folder  {e.plan}")
        print(f"  brief        {brief}")
        started.append((e, brief))
    improve.save_state(INST, {**st, "signals_until": core.now_utc()})
    ensure_generated()
    snapshot(f"improvement round {', '.join(e.name for e, _ in started)}")
    if a.no_run:
        print("  start it:    effort run <round> --role improver --brief <brief>")
        return
    for e, brief in started:
        if a.detach or len(started) > 1:
            run_id = start_run(e, "improver", brief, True, a.minutes, None)
            print(f"  improver run {run_id}: effort wait {run_id}")
        else:
            start_run(e, "improver", brief, False, a.minutes, None)


# ---------------------------------------------------------------- the rest

def cmd_snapshot(a) -> None:
    snapshot(a.message or "snapshot")


def cmd_plan_review(a) -> None:
    from . import plan_review
    e = require_effort(a.name)
    try:
        path = plan_review.generate(e, a.doc)
    except (ValueError, OSError) as exc:
        die(str(exc))
    print(path)
    print(f"  open:  LAVISH_AXI_TELEMETRY=0 npx -y lavish-axi {path}")
    print(f"  wait:  LAVISH_AXI_TELEMETRY=0 npx -y lavish-axi poll {path}")


def cmd_gen(a) -> None:
    if a.check:
        reason = gen.stale_reason(INST)
        print(reason or "current")
        sys.exit(1 if reason else 0)
    try:
        files = gen.generate(INST)
    except gen.GenError as exc:
        die(str(exc))
    print(f"wrote {len(files)} files for instance {INST.name} in {INST.kiro} and {INST.bin}")


def cmd_names(a) -> None:
    print("\n".join(e.name for e in INST.efforts()))


def cmd_roles(a) -> None:
    print("\n".join(INST.roles))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="effort", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance")
    sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("new"); p.add_argument("name"); p.add_argument("--kind", required=True)
    p.add_argument("--base"); p.add_argument("--ticket"); p.add_argument("--branch"); p.add_argument("--no-setup", action="store_true")
    p.set_defaults(fn=cmd_new)
    for n, fn in (("start", cmd_start), ("home", cmd_home)):
        p = sp.add_parser(n)
        if n == "start":
            p.add_argument("name")
        p.add_argument("--terse", action="store_true"); p.add_argument("--resume", action="store_true"); p.set_defaults(fn=fn)
    p = sp.add_parser("run"); p.add_argument("name"); p.add_argument("--role", required=True); p.add_argument("--brief", required=True)
    p.add_argument("--detach", action="store_true"); p.add_argument("--minutes", type=int, default=90); p.add_argument("--model")
    p.set_defaults(fn=cmd_run)
    p = sp.add_parser("_exec"); p.add_argument("name"); p.add_argument("run_id"); p.set_defaults(fn=cmd_exec)
    p = sp.add_parser("wait"); p.add_argument("run_id"); p.add_argument("--timeout", type=int, default=0)
    p.add_argument("--tail", type=int, default=40); p.set_defaults(fn=cmd_wait)
    p = sp.add_parser("logs"); p.add_argument("run_id"); p.add_argument("--tail", type=int, default=200); p.set_defaults(fn=cmd_logs)
    p = sp.add_parser("attach"); p.add_argument("name"); p.set_defaults(fn=cmd_attach)
    p = sp.add_parser("status"); p.add_argument("--collisions", action="store_true"); p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_status)
    p = sp.add_parser("approve"); p.add_argument("name"); p.add_argument("--revoke", action="store_true")
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_approve)
    p = sp.add_parser("close"); p.add_argument("name"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_close)
    p = sp.add_parser("find"); p.add_argument("words", nargs="+"); p.set_defaults(fn=cmd_find)
    p = sp.add_parser("kb"); p.add_argument("action"); p.add_argument("topic"); p.add_argument("text", nargs="+")
    p.add_argument("--effort"); p.add_argument("--role", default="owner"); p.set_defaults(fn=cmd_kb)
    p = sp.add_parser("report"); p.add_argument("text", nargs="+")
    p.add_argument("--scope", default="unsure", choices=improve.SCOPES)
    p.add_argument("--area", default="other"); p.add_argument("--severity", default="friction", choices=improve.SEVERITIES)
    p.add_argument("--effort"); p.add_argument("--role", default="owner"); p.set_defaults(fn=cmd_report)
    p = sp.add_parser("improve"); p.add_argument("action", nargs="?", default="")
    p.add_argument("--scope", default="auto", choices=("auto", "kit", "overlay"))
    p.add_argument("--detach", action="store_true"); p.add_argument("--no-run", action="store_true")
    p.add_argument("--minutes", type=int, default=60); p.set_defaults(fn=cmd_improve)
    p = sp.add_parser("preflight"); p.add_argument("name"); p.add_argument("--fix", action="store_true")
    p.set_defaults(fn=cmd_preflight)
    p = sp.add_parser("plan-review"); p.add_argument("name"); p.add_argument("doc", nargs="?", default="task.md")
    p.set_defaults(fn=cmd_plan_review)
    p = sp.add_parser("gen"); p.add_argument("--check", action="store_true"); p.set_defaults(fn=cmd_gen)
    p = sp.add_parser("snapshot"); p.add_argument("-m", "--message"); p.set_defaults(fn=cmd_snapshot)
    p = sp.add_parser("_names"); p.set_defaults(fn=cmd_names)
    p = sp.add_parser("_roles"); p.set_defaults(fn=cmd_roles)
    return ap


def main(argv: list[str]) -> None:
    global INST
    ap = parser()
    args = ap.parse_args(argv or ["status"])
    if not getattr(args, "fn", None):
        ap.print_help()
        sys.exit(2)
    root = core.find_instance(args.instance)
    if root is None:
        die("no instance here. Name it with --instance <dir> or EFFORTKIT_INSTANCE, or run the instance's bin/effort. "
            "A new project starts with `effortkit installer <dir>`.")
    try:
        INST = core.Instance(root)
    except core.InstanceError as exc:
        die(str(exc))
    args.fn(args)
