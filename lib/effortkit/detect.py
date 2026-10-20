"""Detect the settings of a new instance from the project repository, without a model.

`effortkit init <url-or-path>` writes the answers for `effortkit install`, with the evidence for each value under
`_evidence`. The installer agent then checks the guesses and asks the owner only what a repository cannot show.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from . import core

TICKET = re.compile(r"^(\[)?([A-Z][A-Z0-9]{1,9})-(\d+)(\])?(:?) ")
TAG = re.compile(r"^\[([a-z][a-z0-9-]{1,20})\] ")
CONVENTIONAL = re.compile(r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?: \S")
# A share of the subjects that makes a form the convention. Below it, a form is an accident of some commits.
CONVENTION_SHARE = 0.4
TAG_SHARE = 0.05
# Commands that publish or install into shared places, per ecosystem. The gate refuses them for every role.
PUBLISH = {
    "maven": {"pattern": r"^(mvn|\./mvnw)\b.*\b(install|deploy)\b",
              "reason": "mvn install and mvn deploy write the shared local repository or publish artifacts.",
              "fix": "Run the tests with the test command of the project instead."},
    "gradle": {"pattern": r"^(gradle|\./gradlew)\b.*\bpublish", "reason": "a Gradle publish task publishes artifacts.",
               "fix": "The owner publishes."},
    "node": {"pattern": r"^(npm|pnpm|yarn) +publish\b", "reason": "a publish uploads the package to a registry.",
             "fix": "The owner publishes."},
    "python": {"pattern": r"^(python3? +-m +)?twine +upload\b", "reason": "twine upload publishes the package.",
               "fix": "The owner publishes."},
    "rust": {"pattern": r"^cargo +publish\b", "reason": "cargo publish uploads the crate.", "fix": "The owner publishes."},
    "dotnet": {"pattern": r"^dotnet +nuget +push\b", "reason": "dotnet nuget push publishes the package.",
               "fix": "The owner publishes."},
    "ruby": {"pattern": r"^gem +push\b", "reason": "gem push publishes the gem.", "fix": "The owner publishes."},
}


def run(*args: str, cwd: Path | None = None) -> str:
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=600,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return p.stdout.strip() if p.returncode == 0 else ""


def instance_name(source: str) -> str:
    base = re.split(r"[/:]", str(Path(source).expanduser().resolve()) if Path(source).expanduser().exists()
                    else source.rstrip("/"))[-1].removesuffix(".git")
    name = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:50].strip("-") or "project"
    return name if core.NAME_RE.match(name) else f"{name}-project"[:50]


def open_source(source: str) -> tuple[Path, dict, str, object, bool]:
    """A readable checkout, the repo answers, a note on the choice, a cleanup function, and whether it is in place."""
    p = Path(source).expanduser()
    if p.is_dir() and (p / ".git").exists():
        origin = run("git", "remote", "get-url", "origin", cwd=p)
        if origin:
            note = (f"the clone {p} has the origin {origin}. A bare clone of it keeps your checkout apart from the "
                    "efforts. Set repo.path to use the clone itself.")
            return p, {"url": origin}, note, lambda: None, True
        return p, {"path": str(core.real(p))}, f"the clone {p} has no origin, so the efforts use it in place", \
            lambda: None, True
    tmp = Path(tempfile.mkdtemp(prefix="effortkit-init-"))
    if not run("git", "clone", "-q", "--depth", "300", "--no-tags", source, str(tmp / "repo")) and not (tmp / "repo/.git").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"git clone {source} failed. Check the URL and your access.")
    return tmp / "repo", {"url": source}, f"{source} is a clone source, so the installer makes a bare clone", \
        lambda: shutil.rmtree(tmp, ignore_errors=True), False


def default_branch(checkout: Path, in_place: bool, has_remote: bool) -> str:
    head = run("git", "symbolic-ref", "--short", "HEAD", cwd=checkout) or "main"
    if not has_remote:
        return head  # repo.path without a remote: the efforts branch from a local branch.
    if in_place:
        return run("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=checkout) or f"origin/{head}"
    return f"origin/{head}"


def commit_rules(history: list[tuple[str, str]]) -> tuple[dict, dict, str]:
    """(ticket, commit) answers and the evidence, from the (author, subject) pairs of the history."""
    subjects = [s for _, s in history]
    n = len(subjects)
    if not n:
        return {}, {}, "the history has no commits"
    tickets = [m for m in (TICKET.match(s) for s in subjects) if m]
    conventional = sum(1 for s in subjects if CONVENTIONAL.match(s))
    if tickets and len(tickets) / n >= CONVENTION_SHARE:
        key, _ = Counter(m.group(2) for m in tickets).most_common(1)[0]
        own = [m for m in tickets if m.group(2) == key]
        form, _ = Counter((bool(m.group(1)), m.group(5)) for m in own).most_common(1)[0]
        bracket, colon = form
        prefix = (rf"\[{key}-\d+\]" if bracket else rf"{key}-\d+") + (":" if colon else "") + " "
        shown = (f"[{key}-NNNN]" if bracket else f"{key}-NNNN") + (":" if colon else "") + " <subject>"
        tags = Counter(m.group(1) for m in (TAG.match(s) for s in subjects) if m)
        # A tag that only a bot writes, for example [maven-release-plugin], is no convention for the agents. A tag
        # of the people who also write ticket commits is the form for a commit without a ticket.
        people = {a for a, s in history if TICKET.match(s)}
        users = {tag: {a for a, s in history if (m := TAG.match(s)) and m.group(1) == tag} for tag in tags}
        extra = [t for t, c in tags.items() if c >= 2 and c / n >= TAG_SHARE and users[t] & people]
        bots = sorted(t for t in tags if tags[t] >= 2 and not users[t] & people)
        alternatives = [prefix] + [rf"\[{core.regex_escape(t)}\] " for t in sorted(extra)]
        help_ = " or ".join([shown] + [f"[{t}] <subject>" for t in sorted(extra)])
        example = f"{key}-{own[0].group(3)}"
        rule = "^(?:" + "|".join(alternatives) + r")\S" if len(alternatives) > 1 else "^" + prefix + r"\S"
        evidence = (f"{len(own)} of {n} subjects start with {key}-<number>, for example {own[0].string[:60]!r}"
                    + (f"; tags {', '.join(sorted(extra))} mark commits without a ticket" if extra else "")
                    + (f"; tags {', '.join(bots)} come only from authors with no ticket commit, so the rule leaves them out"
                       if bots else ""))
        return ({"regex": rf"^{key}-\d+$", "example": example},
                {"subject_regex": rule, "subject_help": help_}, evidence)
    if conventional / n >= CONVENTION_SHARE:
        return {}, {"subject_regex": CONVENTIONAL.pattern, "subject_help": "feat: <subject> or fix(<scope>): <subject>"}, \
            f"{conventional} of {n} subjects follow Conventional Commits"
    return {}, {}, f"no prefix is common in the {n} subjects, so any subject passes"


def branch_template(names: list[str], key: str | None) -> tuple[dict, str]:
    if not key or not names:
        return {}, "the default: <ticket>/<name> with a ticket, effort/<name> without one"
    first = sum(1 for b in names if re.match(rf"^{key}-\d+/", b))
    if first and first / len(names) >= 0.3:
        return {"template": "{ticket}/{name}"}, f"{first} of {len(names)} branches start with {key}-<number>/"
    return {}, f"no branch form is common in {len(names)} branches, so the default stays"


def package_json(root: Path) -> dict:
    try:
        return json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def build_and_tests(root: Path) -> tuple[list[str], list[dict], list[str], list[str], list[str]]:
    """(test commands, forbidden commands, tree setup, extra tester globs, evidence lines)."""
    cmds, forbidden, setup, globs, ev = [], [], [], [], []
    if (root / "pom.xml").is_file():
        pom = (root / "pom.xml").read_text(encoding="utf-8", errors="replace")
        mvn = "./mvnw" if (root / "mvnw").is_file() else "mvn"
        cmds.append(f"{mvn} -pl <module> -am test" if "<modules>" in pom else f"{mvn} test")
        forbidden.append(PUBLISH["maven"])
        ev.append(f"pom.xml{' with <modules>' if '<modules>' in pom else ''}: Maven")
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        cmds.append("./gradlew test" if (root / "gradlew").is_file() else "gradle test")
        forbidden.append(PUBLISH["gradle"])
        ev.append("build.gradle: Gradle")
    pkg = package_json(root)
    test_script = (pkg.get("scripts") or {}).get("test", "")
    if pkg:
        manager = "pnpm" if (root / "pnpm-lock.yaml").is_file() else "yarn" if (root / "yarn.lock").is_file() else "npm"
        if test_script and "no test specified" not in test_script:
            cmds.append(f"{manager} test")
            ev.append(f"package.json: the test script runs {test_script!r} with {manager}")
        forbidden.append(PUBLISH["node"])
        lock = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock"}[manager]
        if (root / lock).is_file():
            setup.append({"npm": "npm ci", "pnpm": "pnpm install --frozen-lockfile",
                          "yarn": "yarn install --frozen-lockfile"}[manager])
            ev.append(f"{lock}: each new tree runs {setup[-1]}")
    py = [f for f in ("pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", "setup.py") if (root / f).is_file()]
    uses_pytest = (root / "pytest.ini").is_file() or (root / "conftest.py").is_file() or any(
        "pytest" in (root / f).read_text(encoding="utf-8", errors="replace") for f in py)
    if uses_pytest:
        cmds.append("python3 -m pytest <path>")
        ev.append(f"{', '.join(py) or 'conftest.py'}: pytest")
    elif py or (root / "tests").is_dir() and any((root / "tests").glob("test_*.py")):
        cmds.append("python3 -m unittest discover -s tests")
        ev.append("Python test files without pytest: unittest")
    if py:
        forbidden.append(PUBLISH["python"])
    if (root / "go.mod").is_file():
        cmds.append("go test <packages>")
        ev.append("go.mod: Go")
    if (root / "Cargo.toml").is_file():
        cmds.append("cargo test")
        forbidden.append(PUBLISH["rust"])
        ev.append("Cargo.toml: Rust")
    if list(root.glob("*.sln")) or list(root.glob("*.csproj")):
        cmds.append("dotnet test")
        forbidden.append(PUBLISH["dotnet"])
        ev.append(".sln or .csproj: .NET")
    if (root / "Gemfile").is_file() and (root / "spec").is_dir():
        cmds.append("bundle exec rspec <path>")
        forbidden.append(PUBLISH["ruby"])
        globs += ["spec/**", "**/*_spec.rb"]
        ev.append("Gemfile and spec/: RSpec")
    makefile = root / "Makefile"
    if makefile.is_file():
        targets = set(re.findall(r"^([A-Za-z][\w-]*):", makefile.read_text(encoding="utf-8", errors="replace"), re.M))
        if "test" in targets:
            cmds.append("make test")
            ev.append("Makefile: a test target")
        risky = sorted(targets & {"deploy", "release", "publish", "install"})
        if risky:
            forbidden.append({"pattern": rf"^make\b.*\b({'|'.join(risky)})\b",
                              "reason": f"make {', '.join(risky)} changes something outside the tree.",
                              "fix": "The owner runs it."})
            ev.append(f"Makefile: the targets {', '.join(risky)} are forbidden for the agents")
    return cmds, forbidden, setup, globs, ev


def description(root: Path) -> tuple[str, str]:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        f = root / name
        if not f.is_file():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if not s or s.startswith(("#", "[![", "<", "=", "-", "!", "```", "|", ">")) or set(s) <= set("=-~*"):
                continue
            s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
            s = re.sub(r"[*_`]", "", s)
            end = re.search(r"[.!?](\s|$)", s)
            return (s[:end.end()].strip() if end else s)[:200], f"a guess: the first sentence of {name}, line {n}. Check it"
    return "", "no README with a sentence"


def forge_host(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)[/:]", url)
    return m.group(1) if m and "." in m.group(1) else None


def detect(source: str, name: str | None = None) -> dict:
    checkout, repo, repo_note, cleanup, in_place = open_source(source)
    try:
        answers: dict = {"name": name or instance_name(source)}
        ev: dict = {"repo": repo_note}
        desc, where = description(checkout)
        if desc:
            answers["description"] = desc
        ev["description"] = where
        repo["default_base"] = default_branch(checkout, in_place, "url" in repo)
        answers["repo"] = repo
        ev["repo.default_base"] = "the HEAD of the remote" if not in_place else "the remote HEAD of the clone"
        log = run("git", "log", "--no-merges", "--format=%an%x1f%s", "-n", "300", cwd=checkout).splitlines()
        history = [tuple(line.split("\x1f", 1)) for line in log if "\x1f" in line]
        ticket, commit, ev["commit"] = commit_rules(history)
        if ticket:
            answers["ticket"] = ticket
        if commit:
            answers["commit"] = commit
        key = ticket["regex"][1:].split("-")[0] if ticket else None
        if in_place:
            names = [r.split("/", 1)[1] for r in run("git", "for-each-ref", "--format=%(refname:short)", "refs/remotes",
                                                       cwd=checkout).splitlines() if "/" in r]
        else:
            names = [l.split("refs/heads/", 1)[1] for l in run("git", "ls-remote", "--heads", source).splitlines()
                     if "refs/heads/" in l]
        branch, ev["branch"] = branch_template([b for b in names if b != "HEAD"], key)
        if branch:
            answers["branch"] = branch
        cmds, forbidden, setup, globs, lines = build_and_tests(checkout)
        if cmds:
            answers["tests"] = {"commands": list(dict.fromkeys(cmds))}
        if forbidden:
            answers["forbidden_commands"] = forbidden
        if setup:
            answers["tree_setup"] = setup
        if globs:
            answers["tester_globs"] = core.DEFAULTS["tester_globs"] + globs
        ev["tests"] = "; ".join(lines) or "no build file with a test command. Ask the owner for the test commands."
        host = forge_host(repo.get("url"))
        if host:
            answers["forge"] = {"host": host}
        ev["ask the owner"] = ("models per role, MCP servers per role (effortkit mcp-servers), improve.trigger and "
                               "threshold, style.ste100, project skills and personal steering to copy into the overlay")
        answers["_evidence"] = ev
        return answers
    finally:
        cleanup()
