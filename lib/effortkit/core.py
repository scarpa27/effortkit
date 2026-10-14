"""effortkit core: the kit, an instance and its config, efforts, approvals and runs.

The effort command, the gate hook and the generator import this module.
It is the one place that knows where an instance keeps things.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

# realpath first: trees reach the kit through generated absolute paths, and a link path gives a wrong root.
KIT = Path(os.path.realpath(__file__)).parents[2]
SCHEMA = 1
INSTANCE_FILE = "instance.json"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
STAGES = ("EXPLORING", "RESEARCHING", "INVESTIGATING", "PLANNING", "AWAITING_ANSWERS", "APPROVED",
          "IMPLEMENTING", "TESTING", "REVIEWING", "AWAITING_DECISION", "BLOCKED", "COMPLETE", "ABANDONED")
SUPERVISOR = "supervisor"
INSTALLER = "installer"
# Plan files that only the effort command writes. status.md belongs to the supervisor.
CLI_FILES = ("approval.json", "effort.json", "closed.json")

# A profile decides the tools of a role and its gate rules. Custom roles pick one of these.
PROFILES = {
    "supervisor": {"shell_writer": True, "tree": False, "gated": False, "shell": "trusted"},
    "writer": {"shell_writer": True, "tree": "all", "gated": True, "shell": "trusted"},
    "test-writer": {"shell_writer": True, "tree": "tests", "gated": True, "shell": "trusted"},
    "reader": {"shell_writer": False, "tree": False, "gated": False, "shell": "read"},
    "reader+tests": {"shell_writer": False, "tree": False, "gated": False, "shell": "read+tests"},
    "noshell": {"shell_writer": False, "tree": False, "gated": False, "shell": None},
}

BUILTIN_ROLES = {
    "explorer": {"profile": "reader", "artifact": "exploration-brief.md",
                 "description": "Finds the relevant files, the existing pattern and the constraints before planning"},
    "researcher": {"profile": "reader", "artifact": "research-brief.md", "web": True,
                   "description": "Answers questions from outside the code: documentation, the web, dependency sources"},
    "planner": {"profile": "noshell", "artifact": "task.md and questions.md",
                "description": "Turns a request and the findings into a decision-complete, wave-by-wave plan"},
    "developer": {"profile": "writer", "artifact": "dev-notes.md",
                  "description": "Implements an approved plan in the effort's tree"},
    "tester": {"profile": "test-writer", "artifact": "test-notes.md",
               "description": "Writes and runs the tests of an approved plan"},
    "reviewer": {"profile": "reader+tests", "artifact": "review.md (or the name in your brief)",
                 "description": "Reviews a change: APPROVE or REQUEST_CHANGES"},
    "debugger": {"profile": "reader+tests", "artifact": "investigation.md",
                 "description": "Traces a symptom through the source to a confirmed root cause"},
    "improver": {"profile": "reader", "artifact": "triage.md, task.md and questions.md",
                 "description": "Triages workflow reports and plans fixes to the kit or the project overlay"},
}

# repo: product (the project), kit (this kit), instance (the instance repository) or None (no tree).
BUILTIN_KINDS = {
    "code": {"repo": "product", "stage": "EXPLORING", "lane": "lane-code",
             "about": "a change to the project or a bug fix"},
    "review": {"repo": "product", "stage": "REVIEWING", "lane": "lane-review", "detached": True,
               "about": "a review of somebody's branch in a read-only tree"},
    "triage": {"repo": None, "stage": "INVESTIGATING", "lane": "lane-triage",
               "about": "analysis, research or a question with no code change"},
    "kit": {"repo": "kit", "stage": "EXPLORING", "lane": "lane-kit", "base": "main",
            "about": "a change to the effortkit machinery, which every instance shares"},
    "overlay": {"repo": "instance", "stage": "EXPLORING", "lane": "lane-overlay", "base": "main",
                "about": "a change to this instance: its config, project steering, skills and prompt additions"},
}

DEFAULTS: dict = {
    "effortkit": SCHEMA,
    "name": None,
    "description": "",
    "repo": {"url": None, "path": None, "remote": "origin", "default_base": None},
    "ticket": {"regex": None, "example": None},
    "branch": {"template": "{ticket}/{name}", "fallback": "effort/{name}"},
    "commit": {"subject_regex": r"^\S", "subject_help": "<a short subject>", "forbid_coauthor": True,
               "forbid_dashes": False},
    "push": {"protected_branches": ["main", "master"], "max_tags": 2},
    # commands: examples for the prompts. patterns: full-match regexes over the words of one command.
    "tests": {"commands": [], "patterns": []},
    "tester_globs": ["**/test/**", "**/tests/**", "**/src/test/**", "**/__tests__/**", "**/test_*.py",
                     "**/*_test.py", "**/*_test.go", "**/*.test.*", "**/*.spec.*", "test/**", "tests/**"],
    # Each entry: {"pattern": regex over the words of one command, "reason": text, "fix": text}.
    "forbidden_commands": [],
    "build_dirs": ["target", "build", "dist", "out", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
                   ".tox", ".venv-test", "scratch"],
    "tree_excludes": [],
    # Shell commands that `effort new` runs in a new tree. The owner wrote them, so no gate judges them.
    "tree_setup": [],
    "secrets": {"files": [], "dirs": [], "names": []},
    "max_efforts": 8,
    "models": {"default": "claude-opus-5.5", "tester": "claude-sonnet-5.5", "reviewer": "claude-sonnet-5.5"},
    # role -> list of tool names, for example {"researcher": ["@mcp-web-search"]}.
    "mcp": {},
    # role -> list of SKILL.md globs or folders outside the kit and the overlay.
    "extra_skills": {},
    "roles": {},
    "kinds": {},
    "improve": {"trigger": "on-close", "threshold": 3},
    "style": {"ste100": False},
    "settings": {},
    "forge": {"cli": None, "host": None},
}

# The commit rules of the kit and the instance repositories, which hold workflow machinery, not the project.
WORKFLOW_COMMIT = {"subject_regex": r"^\S", "subject_help": "<a short subject>", "forbid_coauthor": True,
                   "forbid_dashes": False}

HOME = Path.home()
SECRET_FILES = [HOME / ".git-credentials", HOME / ".netrc", HOME / ".npmrc", HOME / ".pypirc",
                HOME / ".docker/config.json", HOME / ".kube/config", HOME / ".m2/settings.xml",
                HOME / ".m2/settings-security.xml", HOME / ".kiroenv",
                # MCP server entries often carry tokens in their env. `effortkit mcp-servers` prints the names only.
                HOME / ".kiro/settings/mcp.json",
                *(HOME / ".local/share/kiro-cli" / f"data.sqlite3{s}" for s in ("", "-wal", "-shm"))]
SECRET_DIRS = [HOME / ".ssh", HOME / ".gnupg", HOME / ".aws", HOME / ".gitlab", HOME / ".config/glab-cli",
               HOME / ".config/gh", HOME / ".password-store", HOME / ".azure", HOME / ".config/gcloud"]
SECRET_NAMES = {".git-credentials", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "id_ecdsa", ".env",
                ".kiroenv"}
# The session environment holds tokens.
PROC_ENVIRON = re.compile(r"^/proc/[^/]+/(task/[^/]+/)?environ$")


class InstanceError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def real(p: Path | str) -> Path:
    return Path(os.path.realpath(p))


def within(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


def resolve(token: str, cwd: Path) -> Path:
    """Resolve a path-like token. A glob keeps only its fixed leading part."""
    s = os.path.expandvars(os.path.expanduser(token))
    parts = []
    for part in s.split("/"):
        if any(c in part for c in "*?["):
            break
        parts.append(part)
    s = "/".join(parts) or ("/" if s.startswith("/") else ".")
    path = Path(s)
    if not path.is_absolute():
        path = cwd / path
    return real(path)


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def read_json(p: Path) -> dict | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json_once(p: Path, data: dict) -> None:
    """Write a record that nobody edits later. A temp file and a rename keep readers from a half file."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".partial.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def merge(base: dict, over: dict) -> dict:
    """Deep merge. A dict merges key by key. Any other value of `over` replaces the base value."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "effortkit"


# ---------------------------------------------------------------- the instance

class Instance:
    """One deployment of the kit for one project. Its root holds instance.json."""

    def __init__(self, root: Path | str):
        self.root = real(root)
        raw = read_json(self.root / INSTANCE_FILE)
        if raw is None or "effortkit" not in raw:
            raise InstanceError(f"{self.root / INSTANCE_FILE} is missing or is not an effortkit instance file")
        if raw.get("effortkit") != SCHEMA:
            raise InstanceError(f"{self.root / INSTANCE_FILE} has schema {raw.get('effortkit')}, the kit reads {SCHEMA}")
        self.raw = raw
        self.config = merge(DEFAULTS, raw)
        self.name = self.config.get("name") or self.root.name
        self.worklog = self.root / "worklog"
        self.plan = self.worklog / "plan"
        self.knowledge = self.worklog / "knowledge"
        self.inbox = self.knowledge / "inbox"
        self.improvements = self.worklog / "improvements"
        self.reports = self.improvements / "inbox"
        self.reports_done = self.improvements / "done"
        self.ledger = self.improvements / "ledger.jsonl"
        self.reference = self.worklog / "reference"
        self.trees = self.root / "trees"
        self.locks = self.root / "locks"
        self.kiro = self.root / ".kiro"
        self.overlay = self.root / "overlay"
        self.bin = self.root / "bin"
        repo_path = self.config["repo"].get("path")
        self.product = real(repo_path) if repo_path else self.root / "product.git"

    # roles and kinds

    @property
    def roles(self) -> dict[str, dict]:
        out = copy.deepcopy(BUILTIN_ROLES)
        for name, spec in (self.config.get("roles") or {}).items():
            if spec is None:
                out.pop(name, None)  # An instance can switch a built-in role off.
            else:
                out[name] = merge(out.get(name, {}), spec)
        return out

    @property
    def kinds(self) -> dict[str, dict]:
        out = copy.deepcopy(BUILTIN_KINDS)
        for name, spec in (self.config.get("kinds") or {}).items():
            out[name] = merge(out.get(name, {}), spec)
        return out

    def profile(self, role: str) -> dict | None:
        if role == SUPERVISOR:
            return PROFILES["supervisor"]
        spec = self.roles.get(role)
        return PROFILES.get(spec.get("profile", "reader")) if spec else None

    def tree_scope(self, role: str) -> tuple[str, ...] | None | bool:
        """None: the whole tree. A tuple: these globs. False: no tree change."""
        prof = self.profile(role)
        if not prof or not prof["tree"]:
            return False
        if prof["tree"] == "all":
            return None
        spec = self.roles.get(role, {})
        return tuple(spec.get("tree_globs") or self.config["tester_globs"])

    def gated(self, role: str) -> bool:
        prof = self.profile(role)
        return bool(prof and prof["gated"])

    def shell_writer(self, role: str) -> bool:
        prof = self.profile(role)
        return bool(prof and prof["shell_writer"])

    def repo_for(self, kind: str) -> Path | None:
        repo = self.kinds.get(kind, {}).get("repo")
        # The kit repository that kit efforts branch from. The tests point it at a scratch clone.
        kit_repo = real(os.environ["EFFORTKIT_KIT_REPO"]) if os.environ.get("EFFORTKIT_KIT_REPO") else KIT
        return {"product": self.product, "kit": kit_repo, "instance": self.root}.get(repo) if repo else None

    def workflow_repo(self, repo: Path | None) -> str | None:
        """"kit" or "instance" when repo holds workflow machinery, else None."""
        if repo is None:
            return None
        r = real(repo)
        kits = {real(KIT)} | ({real(os.environ["EFFORTKIT_KIT_REPO"])} if os.environ.get("EFFORTKIT_KIT_REPO") else set())
        return "kit" if r in kits else "instance" if r == self.root else None

    def commit_rules(self, repo: Path | None) -> dict:
        # The kit is shared, so no instance may change the rules of its hook: two instances would rewrite it in turn.
        which = self.workflow_repo(repo)
        if which == "kit":
            return dict(WORKFLOW_COMMIT)
        if which == "instance":
            return merge(WORKFLOW_COMMIT, {"forbid_dashes": self.config["commit"].get("forbid_dashes", False)})
        return self.config["commit"]

    def push_rules(self, repo: Path | None) -> dict:
        # The machinery repositories belong to the owner alone, so only the tag and the force guards apply there.
        if self.workflow_repo(repo):
            return {"protected_branches": [], "max_tags": self.config["push"].get("max_tags", 2)}
        return self.config["push"]

    def model(self, role: str) -> str | None:
        spec = self.roles.get(role, {})
        return spec.get("model") or self.config["models"].get(role) or self.config["models"].get("default")

    # secrets

    def secret_files(self) -> list[Path]:
        return SECRET_FILES + [Path(os.path.expanduser(p)) for p in self.config["secrets"].get("files", [])]

    def secret_dirs(self) -> list[Path]:
        return SECRET_DIRS + [Path(os.path.expanduser(p)) for p in self.config["secrets"].get("dirs", [])]

    def is_secret(self, p: Path) -> bool:
        names = SECRET_NAMES | set(self.config["secrets"].get("names", []))
        if p.name in names or PROC_ENVIRON.match(str(p)):
            return True
        if any(p == real(f) for f in self.secret_files()):
            return True
        return any(within(p, real(d)) for d in self.secret_dirs())

    # efforts

    def load_effort(self, name: str) -> "Effort | None":
        data = read_json(self.plan / name / "effort.json")
        return Effort(self, name, data) if data is not None else None

    def efforts(self, include_closed: bool = False) -> list["Effort"]:
        out = []
        if self.plan.is_dir():
            for d in sorted(self.plan.iterdir()):
                e = self.load_effort(d.name) if d.is_dir() else None
                if e and (include_closed or not e.closed):
                    out.append(e)
        return out

    def live_session(self, name: str) -> int | None:
        rec = read_json(self.locks / f"{name}.session")
        if rec and isinstance(rec.get("pid"), int) and pid_alive(rec["pid"]):
            return rec["pid"]
        return None


def find_instance(explicit: str | None = None, cwd: Path | str | None = None) -> Path | None:
    """The instance root: --instance, then EFFORTKIT_INSTANCE, then the nearest parent with instance.json and worklog/.

    The worklog/ test matters: a tree of an overlay effort is a checkout of the instance repository, so it holds an
    instance.json too, but the worklog is not tracked there.
    """
    if explicit:
        return real(explicit)
    if os.environ.get("EFFORTKIT_INSTANCE"):
        return real(os.environ["EFFORTKIT_INSTANCE"])
    c = real(cwd or os.getcwd())
    for d in [c, *c.parents]:
        if (d / INSTANCE_FILE).is_file() and (d / "worklog").is_dir():
            return d
    return None


def registry_path() -> Path:
    return config_home() / "instances.json"


def registered_instances() -> list[Path]:
    rec = read_json(registry_path()) or {}
    return [Path(p) for p in rec.get("instances", [])]


def register_instance(root: Path) -> None:
    rec = read_json(registry_path()) or {}
    have = rec.get("instances", [])
    if str(root) not in have:
        have.append(str(root))
    write_json_once(registry_path(), {"instances": sorted(have)})


# ---------------------------------------------------------------- efforts

@dataclass
class Effort:
    inst: Instance
    name: str
    data: dict

    @property
    def plan(self) -> Path:
        return self.inst.plan / self.name

    @property
    def kind(self) -> str:
        return self.data.get("kind", "?")

    @property
    def tree(self) -> Path | None:
        t = self.data.get("tree")
        return Path(t) if t else None

    @property
    def repo(self) -> Path | None:
        r = self.data.get("repo")
        return Path(r) if r else None

    @property
    def closed(self) -> bool:
        return (self.plan / "closed.json").exists()

    def status_field(self, key: str) -> str:
        try:
            for line in (self.plan / "status.md").read_text(encoding="utf-8").splitlines():
                if line.startswith(f"## {key}:"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return ""

    def stage(self) -> str:
        value = self.status_field("Stage")
        return value.split()[0] if value else "?"

    def approval(self) -> tuple[str, str]:
        """Return (state, detail). state is none, stale, valid or no-task."""
        task = sha256_file(self.plan / "task.md")
        if task is None:
            return "no-task", "no task.md"
        rec = read_json(self.plan / "approval.json")
        if not rec:
            return "none", f"task.md {task[:12]} is not approved"
        if rec.get("task_sha256") != task:
            return "stale", f"task.md changed after the approval ({rec.get('task_sha256', '?')[:12]} -> {task[:12]})"
        return "valid", f"approved {rec.get('approved_at', '?')} for task.md {task[:12]}"

    def related(self) -> list[str]:
        try:
            lines = (self.plan / "related.md").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [l.strip("-* ").strip() for l in lines if l.strip("-* ").strip() and not l.startswith("#")]


def pid_alive(pid: int, needle: str = "kiro") -> bool:
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False
    return needle in cmd


def runs_dir(e: Effort) -> Path:
    return e.plan / "runs"


def run_log(e: Effort, run_id: str) -> Path:
    return e.plan / "scratch" / "runs" / f"{run_id}.log"


def run_state(e: Effort, run_id: str) -> tuple[str, int | None]:
    """Return (live|done|lost, exit code). A run without an exit file and without a process is lost."""
    exit_file = runs_dir(e) / f"{run_id}.exit"
    if exit_file.exists():
        try:
            return "done", int(exit_file.read_text().strip() or "-1")
        except ValueError:
            return "done", -1
    pid_file = e.plan / "scratch" / "runs" / f"{run_id}.pid"
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return "lost", None
    return ("live" if pid_alive(pid, "effort") else "lost"), None


def list_runs(e: Effort) -> list[dict]:
    d = runs_dir(e)
    if not d.is_dir():
        return []
    return [r for r in (read_json(p) for p in sorted(d.glob("*.json"))) if r]


# ---------------------------------------------------------------- session context

@dataclass
class Context:
    mode: str                  # home, effort (with a tree), triage (no tree) or install
    effort: Effort | None
    cwd: Path
    error: str | None = None
    extra: dict = field(default_factory=dict)


def resolve_context(inst: Instance, cwd: str | Path | None, env_effort: str | None) -> Context:
    """Find the effort of a session from its directory and EFFORTKIT_EFFORT. The tree decides, the variable must agree."""
    c = real(cwd or os.getcwd())
    trees = real(inst.trees)
    if within(c, trees) and c != trees:
        name = c.relative_to(trees).parts[0]
        if env_effort and env_effort != name:
            return Context("effort", None, c,
                           f"identity mismatch: the session runs in tree '{name}', but EFFORTKIT_EFFORT is '{env_effort}'")
        e = inst.load_effort(name)
        if e is None:
            return Context("effort", None, c, f"tree '{name}' has no effort record. Create efforts with `effort new`.")
        return Context("effort", e, c)
    if within(c, inst.root):
        if env_effort:
            e = inst.load_effort(env_effort)
            if e is None:
                return Context("triage", None, c, f"EFFORTKIT_EFFORT names an unknown effort: '{env_effort}'")
            if e.tree:
                return Context("triage", None, c, f"effort '{env_effort}' has a tree. Start it with `effort start {env_effort}`.")
            return Context("triage", e, c)
        return Context("home", None, c)
    return Context("home", None, c, f"the session directory {c} is outside the instance {inst.root}")


# ---------------------------------------------------------------- repository hooks

def git_common_dir(cwd: Path) -> Path | None:
    """The common git directory of cwd, where the hooks live. A worktree shares it with its repository."""
    for d in [real(cwd), *real(cwd).parents]:
        g = d / ".git"
        if g.is_file():  # A worktree: .git is a file that names the git directory.
            try:
                line = g.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            p = real(Path(line.split(":", 1)[1].strip()) if line.startswith("gitdir:") else d)
            # <repo>/worktrees/<name> holds the per-tree files. The hooks are two levels up.
            return p.parents[1] if p.parent.name == "worktrees" else p
        if g.is_dir():
            return real(g)
        if (d / "HEAD").is_file() and (d / "objects").is_dir():
            return d
    return None
