#!/usr/bin/env python3
"""effortkit hooks: the gates before a tool call, the context for the supervisor, and the end-of-stage duties.

  gate.py --instance <root> pre <role>       preToolUse. Exit 0 allows. Exit 2 refuses, and the agent reads stderr.
  gate.py --instance <root> context          userPromptSubmit for the supervisor. Always exits 0.
  gate.py --instance <root> duties <role>    stop. Always exits 0.
  gate.py --install-target <dir> pre installer   the gate of the installer, which has no instance yet.

The gates stop mistakes, not a hostile agent. A shell command is judged on its text.
"""
from __future__ import annotations

import fnmatch
import glob
import itertools
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(os.path.realpath(__file__)).parents[1]))
    from effortkit import core, improve, repohooks  # noqa: E402
    from effortkit.shellparse import (LITERAL, SUBST, ShellText, split_outer, strip_prefix)  # noqa: E402
else:
    from . import core, improve, repohooks
    from .shellparse import LITERAL, SUBST, ShellText, split_outer, strip_prefix

within, real = core.within, core.real
INST: core.Instance | None = None
INSTALL_TARGET: Path | None = None

BATCH_NOTE = ("If this call was one of several parallel calls, the others failed too. "
              "Repeat each of them alone.")


class Refusal(Exception):
    def __init__(self, gate: str, reason: str, fix: str = ""):
        super().__init__(reason)
        self.gate, self.reason, self.fix = gate, reason, fix


def _mask(text: str) -> str:
    text = re.sub(r"(glpat-|glrt-|ghp_|gho_|github_pat_)[A-Za-z0-9_.-]+", r"\1<masked>", text)
    return re.sub(r"(?i)(bearer|token|password|secret)([\s:=\"']+)\S+", r"\1\2<masked>", text)


def log_path(ctx: core.Context | None) -> Path | None:
    if INST is None:
        return core.config_home() / "install-gate.log"
    if ctx and ctx.effort:
        return ctx.effort.plan / "scratch" / "gate.log"
    return INST.locks / "gate-home.log"


def _log(ctx: core.Context | None, entry: dict) -> None:
    try:
        path = log_path(ctx)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def contract_path() -> str:
    return str(INST.kiro / "steering/workflow-contract.md") if INST else str(core.KIT / "agents/installer.md")


def refuse(role: str, ctx: core.Context | None, tool: str, r: Refusal, detail: str) -> None:
    where = f"{ctx.mode} {ctx.effort.name}" if ctx and ctx.effort else (ctx.mode if ctx else "?")
    _log(ctx, {"time": core.now_utc(), "decision": "refuse", "gate": r.gate, "role": role, "where": where,
               "tool": tool, "reason": r.reason, "call": _mask(detail)[:300]})
    msg = [f"REFUSED by the effortkit {r.gate} gate (role {role}, {where}).", r.reason]
    if r.fix:
        msg.append(r.fix)
    msg += [BATCH_NOTE, f"Rules: {contract_path()}",
            "If this rule is wrong for your task, say so in a workflow report (see the contract) and stop."]
    print("\n".join(msg), file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- scope

def free_tmp(p: Path) -> bool:
    """/tmp is free scratch space, but not when the instance or the kit lives there, as in a test sandbox."""
    if not within(p, real("/tmp")):
        return False
    if within(p, real(core.KIT)):
        return False
    if INST is not None and within(p, INST.root):
        return False
    return not (INSTALL_TARGET and within(p, INSTALL_TARGET))


def zone(p: Path, ctx: core.Context) -> tuple[str, str]:
    if p == Path("/dev/null") or within(p, Path("/dev")):
        return "dev", ""
    if free_tmp(p):
        return "tmp", ""
    e = ctx.effort
    if e and e.tree and within(p, real(e.tree)):
        if within(p, real(e.tree) / ".git"):
            return "protected", "the git internals of the tree"
        return "own-tree", ""
    plan = real(INST.plan)
    if within(p, plan) and p != plan:
        parts = p.relative_to(plan).parts
        name, rest = parts[0], parts[1:]
        if not rest:
            return "protected", "a plan folder itself. `effort new` creates plan folders"
        if rest[0] == "runs" or (len(rest) == 1 and rest[0] in core.CLI_FILES):
            return "protected", f"{'/'.join(rest)}, which only the effort command writes"
        if len(rest) == 1 and rest[0] == "status.md":
            return "status", name
        return ("own-plan" if e and e.name == name else "other-plan"), name
    for base, z in ((INST.inbox, "inbox"), (INST.reports, "inbox"), (INST.knowledge, "knowledge")):
        if within(p, real(base)):
            return z, ""
    for base, label in ((INST.improvements, "the improvement records, which the effort command keeps. "
                                            "Write a report into the improvements inbox instead"),
                        (INST.reference, "the reference material, which is read-only"),
                        (INST.worklog, "the worklog repository, which the effort command commits"),
                        (INST.trees, "the tree of another effort"),
                        (INST.product, "the project repository"),
                        (INST.locks, "the locks of the effort command"),
                        (INST.kiro, "the generated agent configs. Change the kit or the overlay, then run `effort gen`"),
                        (INST.root, "the instance machinery. Change it in an effort of kind overlay"),
                        (core.KIT, "the effortkit machinery. Change it in an effort of kind kit")):
        if within(p, real(base)):
            return "protected", label
    return "outside", ""


def check_secret(p: Path, via: str) -> None:
    secret = INST.is_secret(p) if INST else core.Instance.is_secret(_NO_INSTANCE, p)
    if secret:
        raise Refusal("secrets", f"{via} names {p}, which holds credentials. Agents never read or write it.",
                      "Ask the owner for the value that you need, or for a command that uses it.")


class _NoInstance:
    """Stands in for an instance in the installer gate, so the secret rules come from one place."""
    config = core.merge(core.DEFAULTS, {})

    def secret_files(self):
        return core.SECRET_FILES

    def secret_dirs(self):
        return core.SECRET_DIRS


_NO_INSTANCE = _NoInstance()


def check_target(p: Path, ctx: core.Context, role: str, via: str) -> bool:
    """Raise Refusal when the role may not change p. Return True when the change needs an approved plan."""
    check_secret(p, via)
    if INST is None:
        if free_tmp(p) or within(p, INSTALL_TARGET) or p == Path("/dev/null"):
            return False
        raise Refusal("scope", f"{via} would change {p}. The installer writes only in {INSTALL_TARGET} and /tmp.")
    z, label = zone(p, ctx)
    if z in ("dev", "tmp", "inbox", "own-plan"):
        return False
    if z == "protected":
        raise Refusal("scope", f"{via} would change {p}: {label}.")
    if z == "outside":
        raise Refusal("scope", f"{via} would change {p}, which is outside the instance.",
                      "Write only in your tree, your plan folder, the inboxes or /tmp.")
    if z == "knowledge":
        if role == core.SUPERVISOR:
            return False
        raise Refusal("scope", f"{via} would change {p}. Only the supervisor edits the knowledge topic files.",
                      f"Write the fact into the knowledge inbox: {INST.inbox}/<UTC time>-<effort>-<role>.md")
    if z == "status":
        if role != core.SUPERVISOR:
            raise Refusal("scope", "status.md belongs to the supervisor.",
                          "Report what you finished in your reply and in your artifact.")
        if ctx.mode != "home" and not (ctx.effort and ctx.effort.name == label):
            raise Refusal("scope", f"{via} would change status.md of effort {label}, which is not this session's effort.")
        pid = INST.live_session(label) if ctx.mode == "home" else None
        if pid:
            raise Refusal("scope", f"effort {label} has its own live supervisor session (pid {pid}). That session owns status.md now.")
        return False
    if z == "other-plan":
        if ctx.mode == "home" and role == core.SUPERVISOR:
            return False
        raise Refusal("scope", f"{via} would change the plan folder of effort {label}. A session writes only its own plan folder.",
                      "Read the other effort. Do not write it.")
    # own-tree
    scope = INST.tree_scope(role)
    if scope is False:
        raise Refusal("scope", f"role {role} does not change the tree, and {via} would change {p}.",
                      "Delegate the change to developer, or write into your plan folder.")
    if scope is not None:
        rel = p.relative_to(real(ctx.effort.tree)).as_posix()
        if not any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, g) for g in scope):
            raise Refusal("scope", f"{role} writes only {', '.join(scope)} in the tree. {rel} is outside that.")
    return True


def require_approval(role: str, ctx: core.Context, what: str) -> None:
    if INST is None or not INST.gated(role):
        return
    if not ctx.effort:
        raise Refusal("approval", f"{role} works here without an effort, so no approved plan covers {what}.",
                      f"Start the stage with `effort run <effort> --role {role} --brief <file>`.")
    state, detail = ctx.effort.approval()
    if state != "valid":
        raise Refusal("approval", f"{what} needs an approved plan. {detail}.",
                      f"Only the owner approves: `!effort approve {ctx.effort.name}`. "
                      "Until then you may read, diagnose, run the tests and write into your plan folder.")


# ---------------------------------------------------------------- command rules

GIT_READ = {"status", "log", "diff", "show", "blame", "grep", "ls-files", "ls-tree", "rev-parse", "merge-base",
            "describe", "cat-file", "shortlog", "reflog", "for-each-ref", "rev-list", "show-ref", "name-rev",
            "var", "help", "version", "count-objects", "check-ignore", "whatchanged", "range-diff",
            "diff-tree", "diff-index", "diff-files", "ls-remote", "cherry", "patch-id", "verify-commit",
            "verify-tag", "check-attr", "check-mailmap", "annotate", "stripspace"}
FORGE_READ_ACTIONS = {"list", "view", "status", "trace", "diff", "get", "checks", "ls", "watch"}
# Options of glab api and gh api that make a write. A method other than GET or HEAD does too.
FORGE_API_WRITE = {"-f", "-F", "--field", "--raw-field", "--input"}


def forge_write(verb: str, args: list[str]) -> str:
    """Name the write that a glab or gh call makes, or an empty string when it only reads."""
    plain = [a for a in args if not a.startswith("-")]
    if plain[:1] == ["api"]:
        method = None
        for i, a in enumerate(args):
            if a in ("-X", "--method") and i + 1 < len(args):
                method = args[i + 1].upper()
            elif a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
            elif a.startswith("-X") and len(a) > 2:
                method = a[2:].upper()
        if (method and method not in ("GET", "HEAD")) or any(a in FORGE_API_WRITE for a in args):
            return f"{verb} api with a write method or with fields is refused. The owner changes the forge."
        return ""
    if plain[:1] in (["auth"], ["version"], ["help"], ["--version"]) or not plain:
        return ""
    if len(plain) >= 2 and plain[1] not in FORGE_READ_ACTIONS:
        return f"{verb} {plain[0]} {plain[1]} changes the forge. Agents only read it."
    return ""


EFFORT_HOME_ONLY = {"new", "close", "snapshot", "gen", "improve"}
EFFORT_INTERACTIVE = {"start", "home", "attach"}


def git_parts(words: list[str], cwd: Path) -> tuple[str, list[str], Path, list[str]]:
    i, gcwd, configs = 1, cwd, []
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            gcwd = core.resolve(words[i + 1], gcwd)
            i += 2
        elif w == "-c" and i + 1 < len(words):
            configs.append(words[i + 1])
            i += 2
        elif w.startswith("--work-tree="):
            gcwd = core.resolve(w.split("=", 1)[1], gcwd)
            i += 1
        elif w in ("--work-tree", "--git-dir", "--namespace") and i + 1 < len(words):
            if w == "--work-tree":
                gcwd = core.resolve(words[i + 1], gcwd)
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            break
    return (words[i] if i < len(words) else ""), words[i + 1:], gcwd, configs


def git_is_read(sub: str, args: list[str]) -> bool:
    if sub in GIT_READ:
        return True
    plain = [a for a in args if not a.startswith("-")]
    # "git --version" and "git --help" have no subcommand. git_parts() returns an empty one.
    if not sub:
        return True
    if sub == "fetch":
        # A fetch writes the remote refs of the common repository, which no effort owns. A refspec that writes a
        # local branch, as in "git fetch origin x:y", is a change.
        return not any(":" in a for a in plain[1:])
    if sub == "bundle":
        return bool(plain) and plain[0] in ("verify", "list-heads")
    if sub == "config":
        return any(a in args for a in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin"))
    if sub == "remote":
        return not plain or plain[0] in ("show", "get-url")
    if sub == "branch":
        return not plain or any(a in args for a in ("--list", "-l", "--contains", "--merged", "--no-merged", "--points-at"))
    if sub == "tag":
        return not plain or any(a in args for a in ("-l", "--list", "--contains", "--points-at"))
    if sub in ("stash", "worktree", "notes"):
        return bool(plain) and plain[0] in ("list", "show")
    return False


def branch_backup(plain: list[str], args: list[str], ctx: core.Context) -> bool:
    """True when `git branch <name> [<start>]` only makes a backup of this effort's branch.

    A branch is a pointer, so a new one cannot lose work. It saves work before a history rewrite.
    Delete, rename, force and copy stay refused: those move or drop a pointer.
    """
    own = ctx.effort.data.get("branch") if ctx.effort else None
    if not own or not plain or len(plain) > 2:
        return False
    if any(a.startswith("-") and a not in ("--no-track", "--quiet", "-q") for a in args):
        return False
    return plain[0].startswith(f"{own}-")


def commit_message(args: list[str], gcwd: Path) -> tuple[str | None, bool]:
    """Return (message, explicit). The message is None when the gate cannot know it before the commit runs."""
    msgs, i, reuse = [], 0, False
    while i < len(args):
        a = args[i]
        if a in ("-m", "--message") and i + 1 < len(args):
            msgs.append(args[i + 1]); i += 2; continue
        if a.startswith("--message="):
            msgs.append(a.split("=", 1)[1])
        elif a.startswith("-m") and len(a) > 2 and not a.startswith("--"):
            msgs.append(a[2:])
        elif a.startswith("-") and not a.startswith("--") and a.endswith("m") and len(a) > 2 and i + 1 < len(args):
            msgs.append(args[i + 1]); i += 2; continue
        elif a in ("-F", "--file") and i + 1 < len(args):
            # The commit-msg hook of the repository checks the real message, so an unreadable file is not a refusal.
            try:
                msgs.append(core.resolve(args[i + 1], gcwd).read_text(encoding="utf-8"))
            except OSError:
                return None, True
            i += 2; continue
        elif a.startswith("--file="):
            try:
                msgs.append(core.resolve(a.split("=", 1)[1], gcwd).read_text(encoding="utf-8"))
            except OSError:
                return None, True
        elif a in ("-C", "-c", "--reuse-message", "--reedit-message") or a.startswith(("--reuse-message=", "--fixup", "--squash")):
            reuse = True
        elif a == "--no-edit":
            reuse = True
        i += 1
    if msgs:
        return "\n\n".join(msgs), True
    return None, reuse


TAKES_VALUE = {"-m", "--message", "-F", "--file", "-C", "-c", "--author", "--date", "--cleanup", "-t", "--template",
               "--trailer", "--fixup", "--squash", "--reuse-message", "--reedit-message"}


def repo_of(gcwd: Path, ctx: core.Context) -> Path | None:
    if ctx.effort and ctx.effort.tree and within(gcwd, real(ctx.effort.tree)):
        return ctx.effort.repo
    return None


def check_commit(args: list[str], gcwd: Path, ctx: core.Context) -> None:
    flags, i = [], 0
    while i < len(args):
        a = args[i]
        if a in TAKES_VALUE or (a.startswith("-") and not a.startswith("--") and a.endswith("m") and len(a) > 2):
            flags.append(a)
            i += 2
            continue
        if a.startswith("-") and not (a.startswith(("-m", "-F")) and len(a) > 2 and not a.startswith("--")):
            flags.append(a)
        i += 1
    short = "".join(f[1:] for f in flags if not f.startswith("--"))
    if "--no-verify" in flags or "n" in short:
        raise Refusal("commands", "git commit without its hooks (-n or --no-verify) is refused.")
    repo = repo_of(gcwd, ctx)
    rules = INST.commit_rules(repo) if INST else core.WORKFLOW_COMMIT
    example = f'git commit -m "{rules["subject_help"]}"'
    msg, explicit = commit_message(args, gcwd)
    if msg is None:
        if explicit:
            if INST and repo and repohooks.state(INST, repo) != "ok":
                raise Refusal("commands", "the gate cannot read this message before the commit, and the repository has "
                              f"no current commit-msg hook ({repohooks.state(INST, repo)}).",
                              f"Use {example}, or ask the owner to run `effort preflight <effort> --fix`.")
            return
        raise Refusal("commands", "git commit without -m would open an editor, and a headless session would hang.",
                      f"Use {example}.")
    subject = msg.strip().splitlines()[0] if msg.strip() else ""
    if not re.match(rules["subject_regex"], subject):
        raise Refusal("commands", f"the commit subject must look like {rules['subject_help']!r}. Got: {subject[:80]!r}")
    if rules.get("forbid_coauthor") and re.search(r"(?im)^co-authored-by:", msg):
        raise Refusal("commands", "the commit message has a Co-authored-by line. Commits carry no agent co-author.")
    if rules.get("forbid_dashes") and re.search("[\u2013\u2014]", msg):
        raise Refusal("commands", "the commit message has an em dash or an en dash. Use '-'.")


def forbid(words: list[str], ctx: core.Context, role: str, cwd: Path) -> None:
    verb = os.path.basename(words[0])
    args = words[1:]
    if verb == "sudo":
        raise Refusal("commands", "sudo is refused.")
    if verb in ("pkill", "killall"):
        raise Refusal("commands", f"{verb} can stop other sessions. Name one process id with kill instead.")
    if verb == "tmux" and any(a.startswith("kill-") for a in args):
        raise Refusal("commands", "tmux kill commands are refused. The effort command manages its windows.")
    if verb == "crontab" and any(a in ("-e", "-r") or not a.startswith("-") for a in args):
        raise Refusal("commands", "crontab changes are refused.")
    if verb == "git":
        sub, gargs, gcwd, configs = git_parts(words, cwd)
        bad = next((c for c in configs if GIT_CONFIG_RUNS.match(c)), None)
        if bad:
            raise Refusal("commands", f"git -c {bad.split('=')[0]} makes git run a program or turn a check off.",
                          "Run git without that -c option.")
        if sub == "config" and any(GIT_CONFIG_RUNS.match(a) for a in gargs if not a.startswith("-")) \
                and not git_is_read(sub, gargs):
            raise Refusal("commands", "this git config key makes git run a program or turn a check off.")
        if any("hookspath" in c.lower() for c in configs) or (sub == "config" and any("hookspath" in a.lower() for a in gargs)):
            raise Refusal("commands", "changing core.hooksPath is refused, because it turns the repository hooks off.")
        if sub == "push":
            raise Refusal("commands", "agents never push. The owner pushes and opens the merge request.")
        if sub == "reset" and "--hard" in gargs:
            raise Refusal("commands", "git reset --hard discards work. Use git restore for files, or ask the owner.")
        if sub == "clean" and (any(a.startswith("-") and not a.startswith("--") and "f" in a for a in gargs) or "--force" in gargs):
            raise Refusal("commands", "git clean -f deletes untracked files and is refused.")
        plain = [a for a in gargs if not a.startswith("-")]
        if INST is not None:
            if sub == "branch" and not git_is_read(sub, gargs) and not branch_backup(plain, gargs, ctx):
                raise Refusal("commands", "agents do not create, rename or delete branches. The effort command manages them.",
                              "A backup of this effort's branch is allowed: git branch <effort branch>-<suffix>.")
            if sub in ("checkout", "switch"):
                if any(a in ("-b", "-B", "-c", "-C", "--orphan") for a in gargs):
                    raise Refusal("commands", "agents do not create branches. Stay on the effort branch.")
                if "--" not in gargs and ((plain and plain != ["."]) or "-" in gargs):
                    raise Refusal("commands", f"git {sub} {' '.join(plain or ['-'])} would leave the effort branch.",
                                  "Stay on the effort branch. Restore files with: git restore <path>")
            if sub == "worktree" and not git_is_read(sub, gargs):
                raise Refusal("commands", "the effort command creates and removes trees, not agents.")
            if sub == "tag" and not git_is_read(sub, gargs):
                raise Refusal("commands", "agents do not create tags.")
        if sub == "rebase" and any(a in ("-i", "--interactive") for a in gargs):
            raise Refusal("commands", "git rebase -i opens an editor and would hang a headless session.")
        if sub in ("update-ref", "filter-branch", "filter-repo", "replace"):
            raise Refusal("commands", f"git {sub} rewrites history or refs and is refused.")
        if sub == "commit":
            check_commit(gargs, gcwd, ctx)
    if verb in ("glab", "gh"):
        write = forge_write(verb, args)
        if write and role != core.SUPERVISOR:
            raise Refusal("commands", write, "Draft the text in your artifact. The supervisor posts it after the owner says yes.")
    if verb in ("curl", "wget"):
        upload = {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form", "-T",
                  "--upload-file", "--post-data", "--post-file", "--json"}
        method = next((args[i + 1].upper() for i, a in enumerate(args) if a in ("-X", "--request", "--method") and i + 1 < len(args)), None)
        if any(a in upload or a.startswith(("--data", "--form", "--post-")) for a in args) or (method and method not in ("GET", "HEAD")):
            raise Refusal("commands", f"{verb} would send data out. Agents do not upload project data.")
        if verb == "curl":
            hidden = short_opt(args, "K", "AbcCdDeEFHmoPQrTuUwxXyYz") or any(a.startswith("--config") for a in args)
        else:
            hidden = short_opt(args, "e", "oaiBOPtTwQlARDIXU") or any(a.startswith(("--execute", "--config")) for a in args)
        if hidden:
            raise Refusal("commands", f"{verb} would read options from a file or a command, and the gate cannot check them.",
                          "Put each option on the command line.")
    if verb == "rm" and any(a in ("-r", "-R", "--recursive") or (a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a)) for a in args):
        build_dirs = set(INST.config["build_dirs"]) if INST else set(core.DEFAULTS["build_dirs"])
        for t in (a for a in args if not a.startswith("-")):
            p = core.resolve(t, cwd)
            ok = free_tmp(p) or any(part in build_dirs for part in p.parts) or (INST is None and within(p, INSTALL_TARGET))
            if not ok:
                raise Refusal("commands", f"rm -r is allowed only on build folders ({', '.join(sorted(build_dirs))}) or /tmp. Refused: {p}")
    if verb == "find":
        start = next((a for a in args if not a.startswith("-")), ".")
        if start in ("/", "~", "/repo", "/home", "/proc") and "-maxdepth" not in args:
            raise Refusal("commands", f"find {start} without -maxdepth can run for hours. Name a smaller folder or add -maxdepth.")
    if verb == "effort" or (verb.startswith("python") and args and args[0].endswith("/effort")):
        eargs = args[1:] if verb != "effort" else args
        eargs = [a for a in eargs if not a.startswith("--instance")]
        sub = eargs[0] if eargs else "status"
        if sub == "approve":
            raise Refusal("commands", "only the owner approves a plan. An agent never runs effort approve.")
        if sub in EFFORT_INTERACTIVE:
            raise Refusal("commands", f"effort {sub} is interactive. The owner runs it in a terminal.")
        if sub == "run" and role != core.SUPERVISOR:
            raise Refusal("commands", "only the supervisor starts stages. Report what the next stage needs in your reply.")
        if ctx.mode != "home":
            if sub in EFFORT_HOME_ONLY and not (sub == "improve" and eargs[1:2] == ["stats"]):
                raise Refusal("commands", f"effort {sub} runs from the home chat, not from inside an effort.")
            target_effort = next((a for a in eargs[1:] if not a.startswith("-")), None)
            if sub in ("run", "plan-review") and target_effort and ctx.effort and target_effort != ctx.effort.name:
                raise Refusal("commands", f"this session belongs to effort {ctx.effort.name}. It runs stages only for its own effort.")
    if INST is not None:
        line = " ".join(words)
        for rule in INST.config.get("forbidden_commands") or []:
            if re.search(rule["pattern"], line):
                raise Refusal("commands", rule.get("reason") or f"this command matches the forbidden pattern {rule['pattern']!r}.",
                              rule.get("fix", ""))


# ---------------------------------------------------------------- mutation analysis

READ_VERBS = {"cat", "head", "tail", "less", "more", "wc", "grep", "egrep", "fgrep", "rg", "ls", "tree", "pwd", "echo",
              "printf", "jq", "yq", "diff", "cmp", "file", "stat", "sort", "uniq", "cut", "awk", "sed", "tr", "basename",
              "dirname", "realpath", "readlink", "which", "type", "test", "[", "true", "false", "date", "printenv", "id",
              "whoami", "hostname", "uname", "du", "df", "sha256sum", "sha1sum", "md5sum", "xmllint", "column", "nl",
              "fold", "tac", "rev", "comm", "join", "paste", "seq", "sleep", "ps", "pgrep", "getent", "zcat", "zgrep",
              "hexdump", "od", "xxd", "strings", "nproc", "free", "uptime", "kill", "ping", "host", "dig", "bc", "expr",
              "zipinfo", "pip", "pip3", "openssl", "npm"}
MUTATE_ALL = {"rm", "rmdir", "touch", "mkdir", "truncate", "shred", "unlink", "tee"}
MUTATE_SKIP_FIRST = {"chmod", "chown", "chgrp"}
# python -m <module>: these read. Every other python call runs code that the gate does not see.
PYTHON_READ_MODULES = {"unittest", "pytest", "zipfile", "json.tool", "site", "sysconfig", "platform"}
MUTATE_LAST = {"cp", "mv", "ln", "install", "rsync", "scp"}
EFFORT_READ = {"status", "find", "logs", "wait", "preflight", "help", "_names", "_roles", "kb", "report", "plan-review", "run"}
NPM_READ = {"view", "info", "ls", "list", "outdated", "help", "config"}
SHORT = re.compile(r"^-[A-Za-z.]+$")
# Options of pip download that take a value, so the value is not read as a requirement.
PIP_VALUE = {"-d", "--dest", "-i", "--index-url", "--extra-index-url", "-f", "--find-links", "--platform",
             "--python-version", "--implementation", "--abi", "--only-binary", "--no-binary", "-c", "--constraint",
             "--cache-dir", "--progress-bar", "--timeout", "--retries", "--proxy", "--trusted-host", "--cert",
             "--client-cert", "--log", "--exists-action", "--src", "--report", "--python"}


def options(args: list[str]) -> list[str]:
    """The arguments before a bare --, after which every argument is a name."""
    return args[:args.index("--")] if "--" in args else args


def short_opt(args: list[str], letters: str, takes_value: str = "") -> bool:
    """True when one of the short options appears alone, bundled (-ro) or with an attached value (-ofile)."""
    for a in options(args):
        if not a.startswith("-") or a.startswith("--") or a == "-":
            continue
        for c in a[1:]:
            if c in letters:
                return True
            if c in takes_value:
                break
    return False


# The w command of sed, as "s/a/b/w file", "/x/w file" or "2w file". The W command writes too.
SED_WRITE = re.compile(r"(?:/[gpimIM0-9]*|^|[;{}\n]\s*[0-9,$~+*/^]*)\s*[wW]\s+\S")
FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
GIT_CONFIG_RUNS = re.compile(r"^(?:alias\.|core\.(?:pager|editor|sshCommand|askPass|hooksPath|fsmonitor|externalDiff)"
                             r"|sequence\.editor|diff\.external|.*\.textconv|.*\.process|credential\.helper"
                             r"|uploadpack\.|receivepack\.|protocol\.|http\.proxy)", re.I)


def read_effect(verb: str, args: list[str]) -> str:
    """Name the flag that makes a read command run a program, write a file or print the environment."""
    opts = options(args)
    if verb == "rg" and any(a in ("--pre", "--hostname-bin") or a.startswith(("--pre=", "--hostname-bin=")) for a in opts):
        return "rg --pre and --hostname-bin run a program"
    # GNU tools accept any unique prefix of a long option, so --co is --compress-program and --o is --output.
    if verb == "sort" and any(a.startswith("--co") for a in opts):
        return "sort --compress-program runs a program"
    if verb == "sort" and (any(a.startswith("--o") for a in opts) or short_opt(args, "o", "ktST")):
        return "sort -o writes a file"
    if verb == "tree" and any(a.startswith("-") and not a.startswith("--") and "o" in a[1:] for a in opts):
        return "tree -o writes a file"
    if verb == "uniq" and len([a for a in args if not a.startswith("-") and not a.isdigit()]) > 1:
        return "uniq with two file names writes the second one"
    if verb == "jq" and any(re.search(r"(^|[^.\w$])env\b|\$ENV\b", a) for a in args):
        return "jq env prints the environment, which holds tokens"
    if verb in ("sed", "awk") and (short_opt(args, "f", "eis") or any(a.startswith(("--file", "--source")) for a in opts)):
        return f"{verb} -f runs a script from a file, which the gate does not see"
    if verb == "sed" and any(SED_WRITE.search(a) for a in args if not a.startswith("-")):
        return "the w command of sed writes a file"
    if verb == "awk" and any(re.search(r">[^=]|\|\s*[\"']|\bsystem\s*\(|\bENVIRON\b", a) for a in args if not a.startswith("-")):
        return "this awk script redirects, runs a command or reads the environment"
    if verb == "find" and any(a in FIND_ACTIONS or a.startswith(tuple(f"{x}=" for x in FIND_ACTIONS)) for a in opts):
        return f"find {', '.join(sorted(FIND_ACTIONS))} runs a program or writes a file"
    if verb in ("pip", "pip3") and args[:1] == ["download"]:
        return pip_download_effect(args)
    if verb == "printenv" or (verb == "env" and not args):
        return f"{verb} prints the environment, which holds tokens"
    return ""


def pip_download_effect(args: list[str]) -> str:
    """pip runs the setup code of a package that it must build, so a read-only download takes wheels only."""
    reqs, i = [], 1
    while i < len(args):
        if args[i] in PIP_VALUE:
            i += 2
            continue
        if not args[i].startswith("-"):
            reqs.append(args[i])
        i += 1
    wheels = "--only-binary=:all:" in args or any(a == "--only-binary" and args[j + 1:j + 2] == [":all:"]
                                                  for j, a in enumerate(args))
    builds = short_opt(args, "re", "difc") or any(
        a.startswith(("--requirement", "--editable", "--no-binary")) for a in args)
    if not wheels or builds or any("/" in r or ":" in r or r.startswith((".", "~")) for r in reqs):
        return ("pip download builds a package unless it takes wheels only. Add --only-binary=:all:, "
                "and name packages, not paths, URLs or requirement files")
    return ""


def hidden_reads(verb: str, args: list[str], cwd: Path) -> list[Path]:
    """The folders that a command reads recursively with hidden files. A credential below one of them leaks."""
    opts = options(args)
    if verb == "rg":
        u = sum(a.count("u") for a in opts if SHORT.match(a)) + opts.count("--unrestricted")
        on = u >= 2 or "--hidden" in opts or any(SHORT.match(a) and "." in a for a in opts)
    elif verb in ("grep", "egrep", "fgrep"):
        on = short_opt(args, "rR", "efmABCdD") or any(a in ("--recursive", "--dereference-recursive", "--directories=recurse")
                                                    for a in opts) or ("-d" in opts and "recurse" in args)
    elif verb == "diff":
        on = short_opt(args, "r", "xXIFSUCLDW") or "--recursive" in opts
    else:
        on = False
    if not on:
        return []
    named = [p for p in (core.resolve(a, cwd) for a in args if not a.startswith("-")) if p.exists()]
    return [p for p in named if p.is_dir()] if named else [cwd]


def braces(tok: str, limit: int = 64) -> list[str]:
    """Expand {a,b} as bash does, innermost first, so a brace cannot hide a credential path from the gate."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", tok)
    if not m:
        return [tok]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out += braces(tok[:m.start()] + alt + tok[m.end():], limit)
        if len(out) >= limit:
            break
    return out[:limit]


def is_shell_writer(role: str) -> bool:
    return INST.shell_writer(role) if INST else role == core.INSTALLER


def expand_path(tok: str, cwd: Path, role: str) -> list[Path]:
    """The paths that a token reaches after brace and glob expansion, so neither can hide a credential file."""
    alts = braces(tok)
    if not is_shell_writer(role) and any(re.search(r"\{[^{}]*\.\.[^{}]*\}", t) for t in alts):
        raise Refusal("secrets", f"the gate cannot check the brace range in {tok}.", "Name the paths one by one.")
    out = []
    for t in alts:
        out.append(core.resolve(t, cwd))
        if any(ch in t for ch in "*?["):
            pat = os.path.expanduser(t)
            pat = pat if os.path.isabs(pat) else os.path.join(str(cwd), pat)
            out += [real(m) for m in itertools.islice(glob.iglob(pat), 5000)]
    return out


def agent_writable(p: Path) -> bool:
    """A folder where a role with a read-only shell can create files."""
    if free_tmp(p):
        return True
    return INST is not None and (within(p, real(INST.plan)) or within(p, real(INST.inbox)) or within(p, real(INST.reports)))


def value_after(args: list[str], *opts: str) -> str | None:
    for i, a in enumerate(args):
        if a in opts and i + 1 < len(args):
            return args[i + 1]
        for o in opts:
            if o.startswith("--") and a.startswith(o + "="):
                return a.split("=", 1)[1]
    return None


def target(tok: str, cwd: Path) -> tuple[Path, str]:
    """A write target: the resolved path, and the token as written. A token with SUBST has no resolvable path."""
    return core.resolve(clean(tok), cwd), tok


def is_test_command(words: list[str]) -> bool:
    if INST is None or not words:
        return False
    line = " ".join(words)
    return any(re.fullmatch(p, line) for p in INST.config["tests"].get("patterns") or [])


def analyze(words: list[str], out: list[str], cwd: Path) -> dict:
    r = {"targets": [target(t, cwd) for t in out], "git": None, "opaque": False, "cwd": None, "inner": [], "verb": "",
         "effect": "", "workdir": None, "test": False}
    words = [clean(x) for x in words]
    w = strip_prefix(words)
    if not w:
        return r
    verb = os.path.basename(w[0])
    a = w[1:]
    plain = [x for x in a if not x.startswith("-")]
    r["verb"] = verb
    r["effect"] = read_effect(verb, a)
    if is_test_command(w):
        # A test runner reads code and settings from its working folder, so it must not run where agents write.
        r["test"], r["workdir"] = True, cwd
        return r
    if verb in ("git", "glab", "gh", "npm") or (re.match(r"^python3?(\.\d+)?$", verb) and "-m" in a):
        # These read code or settings from their working folder, so a folder that an agent can write is not safe.
        r["workdir"] = cwd
    if verb in ("cd", "pushd"):
        r["cwd"] = core.resolve(plain[0], cwd) if plain else core.HOME
    elif verb in ("bash", "sh", "zsh", "dash") and "-c" in a:
        i = a.index("-c")
        r["inner"].append(a[i + 1] if i + 1 < len(a) else "")
    elif verb == "script":
        # script -c "<command>" runs the command with a shell, so the gate judges that text.
        i = next((k for k, x in enumerate(a) if x in ("-c", "--command")
                  or (x.startswith("-") and not x.startswith("--") and x.endswith("c"))), None)
        r["inner"].append(a[i + 1] if i is not None and i + 1 < len(a) else next((x for x in plain), ""))
    elif re.match(r"^python3?(\.\d+)?$", verb):
        r["opaque"] = value_after(a, "-m") not in PYTHON_READ_MODULES
    elif verb == "eval":
        r["inner"].append(" ".join(a))
    elif verb == "xargs":
        rest = list(a)
        while rest and rest[0].startswith("-"):
            rest.pop(0)
        if rest:
            sub = analyze(rest, [], cwd)
            sub["targets"] += [(cwd, str(cwd))] if os.path.basename(rest[0]) in MUTATE_ALL | MUTATE_LAST | MUTATE_SKIP_FIRST else []
            sub["targets"] += r["targets"]
            return sub
    elif verb == "git":
        sub, gargs, gcwd, _ = git_parts(w, cwd)
        gplain = [x for x in gargs if not x.startswith("-")]
        if sub in ("clone", "init"):
            # These create a repository in a new folder, so that folder is the write target, not the working folder.
            # A value option such as --depth 50 leaves its value among the plain words, and the folder comes last.
            if sub == "clone":
                dest = gplain[-1] if len(gplain) >= 2 else (gplain[0].rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
                                                           if gplain else ".")
            else:
                dest = gplain[-1] if gplain else "."
            r["targets"].append(target(dest, gcwd))
        elif not git_is_read(sub, gargs):
            r["git"] = (sub, gcwd)
        if sub == "grep" and (short_opt(gargs, "O", "efABCm") or any(x.startswith("--op") for x in options(gargs))):
            r["effect"] = "git grep -O runs a program"
        elif any(x == "--output" or x.startswith("--output=") for x in options(gargs)):
            r["effect"] = "git --output writes a file"
        r["workdir"] = gcwd
    elif verb in ("sed", "perl") and any(x == "-i" or x.startswith(("-i", "--in-place")) for x in a):
        files = list(plain)
        if not any(x in ("-e", "--expression", "-f") for x in a):
            files = files[1:]
        r["targets"] += [target(f, cwd) for f in files]
    elif verb in MUTATE_ALL:
        r["targets"] += [target(f, cwd) for f in plain]
    elif verb in MUTATE_SKIP_FIRST:
        r["targets"] += [target(f, cwd) for f in plain[1:]]
    elif verb in MUTATE_LAST:
        r["targets"] += [target(f, cwd) for f in plain[-1:]]
    elif verb == "dd":
        r["targets"] += [target(x[3:], cwd) for x in a if x.startswith("of=")]
    elif verb == "tar" and any(x in ("-x", "--extract", "--get") or (not x.startswith("--") and "x" in x.lstrip("-") and x == (a[0] if a else "")) for x in a):
        r["targets"].append(target(value_after(a, "-C", "--directory") or ".", cwd))
    elif verb == "unzip" and not any(x in ("-l", "-p", "-t", "-v", "-Z") for x in a):
        r["targets"].append(target(value_after(a, "-d") or ".", cwd))
    elif verb in ("curl", "wget"):
        dest = value_after(a, "-o", "--output") if verb == "curl" else value_after(a, "-O", "--output-document")
        if dest and dest != "-":
            r["targets"].append(target(dest, cwd))
        elif (verb == "curl" and any(x in ("-O", "--remote-name", "-J") for x in a)) or (verb == "wget" and dest is None):
            r["targets"].append(target(value_after(a, "-P", "--directory-prefix") or ".", cwd))
    elif verb == "find":
        if "-delete" in a:
            r["targets"] += [target(x, cwd) for x in a[:next((i for i, x in enumerate(a) if x.startswith(("-", "(", "!"))), len(a))]] or [(cwd, str(cwd))]
        if any(x in ("-exec", "-execdir", "-ok", "-okdir") for x in a):
            r["opaque"] = True
    elif verb in ("glab", "gh"):
        # forbid() already refused a write for every role but the supervisor.
        r["opaque"] = bool(forge_write(verb, a))
    elif verb in ("pip", "pip3") and plain[:1] == ["download"]:
        r["targets"].append(target(value_after(a, "-d", "--dest") or ".", cwd))
    elif verb in ("pip", "pip3"):
        r["opaque"] = plain[:1] not in (["index"], ["show"], ["list"])
    elif verb == "npm":
        r["opaque"] = plain[:1] == [] or plain[0] not in NPM_READ
    elif verb == "effort":
        sub = plain[0] if plain else "status"
        r["opaque"] = sub not in EFFORT_READ and not (sub == "improve" and plain[1:2] == ["stats"])
    elif verb == "kiro-cli":
        r["opaque"] = plain[:1] not in (["agent"], ["settings"]) and not any(x in ("--version", "--help") for x in a)
    elif verb not in READ_VERBS:
        r["opaque"] = True
    return r


def looks_like_path(tok: str) -> bool:
    names = core.SECRET_NAMES | (set(INST.config["secrets"].get("names", [])) if INST else set())
    return "/" in tok or tok.startswith(("~", ".", "$HOME")) or tok in names


VAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def expand_vars(tok: str, env: dict[str, str]) -> str:
    """Replace the variables that this command set. An unknown name becomes SUBST, so the gate cannot read it as text."""
    return REF.sub(lambda m: env.get(m.group(1), SUBST), tok)


def assignment(words: list[str], env: dict[str, str]) -> None:
    """Record the leading NAME=value assignments of one simple command.

    A value keeps the SUBST marker of a part that the gate cannot know, as in B=/tmp/x-$T.bak. The folder of such a
    path is still known, and that decides the zone.
    """
    for w in words:
        m = VAR.match(w)
        if not m:
            return
        env[m.group(1)] = m.group(2).replace(LITERAL, "$")


def clean(tok: str) -> str:
    return tok.replace(LITERAL, "$")


APPROVE_CMD = re.compile(r"(?:^|[;&|(\n]|&&|\|\|)\s*!?\s*(?:\S*/)?effort\s+(?:--instance\S*\s+\S*\s+)?approve\b")


def check_shell(cmd: str, ctx: core.Context, role: str, cwd: Path, depth: int = 0, env: dict[str, str] | None = None) -> list[str]:
    """Raise Refusal for a refused command. Return what needs an approved plan."""
    if depth > 3 or not cmd.strip():
        return []
    # Text-level, because a wrapper such as script -c or python -c hides the command from the word analysis.
    # APPROVE_CMD needs a command position, so a message that tells the owner to run the command is not a match.
    writes_approval = re.search(r"(>>?\s*|\btee\s+(-a\s+)?|\b(cp|mv|install|ln)\b[^;&|\n]*\s)\S*approval\.json", cmd) \
        or re.search(r"approval\.json['\"]\s*,\s*['\"][wax]", cmd)
    if APPROVE_CMD.search(cmd) or writes_approval:
        raise Refusal("commands", "only the owner approves a plan. An agent never runs effort approve or writes approval.json.")
    try:
        text = ShellText(cmd)
        cmds = split_outer(text.parse())
    except ValueError as exc:
        raise Refusal("commands", f"the gate cannot parse this command: it has {exc}.",
                      "Simplify it, or write the file with the write tool.")
    needs: list[str] = []
    for inner in text.inner:
        needs += check_shell(inner, ctx, role, cwd, depth + 1)
    eff, env = cwd, dict(env or {})
    secret_files = INST.secret_files() if INST else core.SECRET_FILES
    secret_dirs = INST.secret_dirs() if INST else core.SECRET_DIRS
    for c in cmds:
        words = [expand_vars(w, env) for w in c["words"]]
        out = [expand_vars(w, env) for w in c["out"]]
        assignment(words, env)
        verbs = strip_prefix(words)
        for tok in words + out:
            if looks_like_path(tok) or any(ch in tok for ch in "*?[{"):
                for p in expand_path(clean(tok), eff, role):
                    check_secret(p, "this command")
        if verbs:
            forbid([clean(w) for w in verbs], ctx, role, eff)
            verb = os.path.basename(clean(verbs[0]))
            for d in hidden_reads(verb, [clean(w) for w in verbs[1:]], eff):
                leak = next((s for s in secret_files + secret_dirs if within(real(s), d)), None)
                if leak:
                    raise Refusal("secrets", f"`{verb}` reads hidden files below {d}, and {leak} there holds credentials.",
                                  "Use rg -u (one u), which skips hidden folders, or name a narrower folder.")
        r = analyze(words, out, eff)
        if r["cwd"] is not None:
            eff = r["cwd"]
            continue
        writer = is_shell_writer(role)
        if r["effect"]:
            if not writer:
                raise Refusal("scope", f"role {role} has a read-only shell, and {r['effect']}.",
                              "Drop the flag. To keep a result, write it with the write tool into your plan folder.")
            needs.append(r["effect"])
        if r["test"] and not writer and (INST is None or (INST.profile(role) or {}).get("shell") != "read+tests"):
            raise Refusal("commands", f"role {role} does not run the tests.",
                          "Report what the next stage needs. The reviewer, the debugger and the tester run tests.")
        if r["workdir"] and not writer and agent_writable(r["workdir"]):
            raise Refusal("scope", f"{r['verb']} reads its settings from {r['workdir']}, and agents can write files there. "
                          "A planted settings file there runs programs.",
                          f"Run {r['verb']} in the tree or in the instance root.")
        for inner in r["inner"]:
            needs += check_shell(inner, ctx, role, eff, depth + 1, env)
        for t, raw in r["targets"]:
            if SUBST in raw + str(t) and not free_tmp(t):
                raise Refusal("scope", f"`{r['verb'] or 'a redirect'}` would write {raw.replace(SUBST, '?') or t}, "
                              "and the gate cannot resolve that path.",
                              "Set the variable in the same command (VAR=/absolute/path), or write the path out in full.")
            if check_target(t, ctx, role, f"`{r['verb'] or 'a redirect'}`"):
                needs.append(f"changing {t}")
        if r["git"]:
            sub, gcwd = r["git"]
            if INST is None:
                if not (within(gcwd, INSTALL_TARGET) or free_tmp(gcwd)):
                    raise Refusal("scope", f"git {sub} would change the repository at {gcwd}. The installer changes only "
                                  f"repositories in {INSTALL_TARGET}.")
            else:
                if INST.tree_scope(role) is False:
                    raise Refusal("scope", f"role {role} does not change a repository (git {sub}).",
                                  "Delegate the change to developer.")
                tree = ctx.effort.tree if ctx.effort else None
                if not (tree and within(gcwd, real(tree))):
                    raise Refusal("scope", f"git {sub} would change the repository at {gcwd}, which is not this effort's tree.")
                needs.append(f"git {sub}")
        if r["opaque"]:
            if not writer and not (INST and INST.gated(role)):
                raise Refusal("commands", f"`{r['verb']}` is not one of the read commands of role {role}, "
                              "and only a writer role runs another program.",
                              "Report what the next stage needs, or ask the supervisor to run it in a writer stage.")
            needs.append(f"the command `{r['verb']}`")
    return needs


# ---------------------------------------------------------------- handlers

PATH_KEYS = {"path", "paths", "file_path", "filepath", "image_paths", "directory", "dir", "file"}


def tool_paths(obj, tool: str) -> list[str]:
    found: list[str] = []

    def walk(o, key=None):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str) and (key in PATH_KEYS or (tool == "glob" and key == "pattern")):
            found.append(o)
    walk(obj)
    return found


MCP_READ_WORDS = {"get", "search", "list", "download", "read", "fetch", "find", "view", "lookup", "query", "show",
                  "describe", "summaries", "content", "status", "chat"}
MCP_WRITE_WORDS = {"create", "update", "delete", "remove", "add", "edit", "post", "put", "patch", "transition",
                   "assign", "move", "merge", "close", "reopen", "comment", "upload", "publish", "write", "set", "send",
                   "approve", "link", "unlink", "batch", "rename", "archive", "deploy", "trigger", "run"}


def check_mcp(tool: str, role: str) -> None:
    """A change in a ticket system, a wiki or a forge is visible to the whole team, like a post. A tool name with a
    read word reads. A name with a write word and no read word changes something, and only the supervisor does that."""
    _, _, name = tool[1:].partition("/")
    words = set(re.split(r"[_\-.]+", name.lower()))
    if role != core.SUPERVISOR and not (words & MCP_READ_WORDS) and words & MCP_WRITE_WORDS:
        raise Refusal("commands", f"{name} changes a shared system, which the whole team sees.",
                      "Draft the change in your artifact. The supervisor applies it after the owner says yes.")


def read_payload() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def pre(role: str) -> None:
    payload = read_payload()
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    detail = json.dumps(ti, ensure_ascii=False)
    if INST is None:
        ctx = core.Context("install", None, real(payload.get("cwd") or os.getcwd()))
    else:
        ctx = core.resolve_context(INST, payload.get("cwd"), os.environ.get("EFFORTKIT_EFFORT"))
    if os.environ.get("EFFORTKIT_GATE_DEBUG"):
        _log(ctx, {"time": core.now_utc(), "decision": "seen", "role": role, "tool": tool,
                   "keys": sorted(payload), "input_keys": sorted(ti) if isinstance(ti, dict) else type(ti).__name__})
    try:
        if ctx.error:
            raise Refusal("identity", ctx.error, "Start sessions with the effort command: effort home, effort start or effort run.")
        if INST is not None and role != core.SUPERVISOR and role not in INST.roles:
            raise Refusal("identity", f"role {role} is not a role of instance {INST.name}.", "Run `effort gen`.")
        cwd = ctx.cwd
        if tool in ("write", "fs_write"):
            paths = tool_paths(ti, tool)
            if not paths:
                raise Refusal("scope", "the write call names no path.")
            needs = [p for p in paths if check_target(core.resolve(p, cwd), ctx, role, "the write tool")]
            if needs:
                require_approval(role, ctx, f"writing {', '.join(needs[:3])}")
        elif tool == "code":
            paths = tool_paths(ti, tool) or ["."]
            if ti.get("operation") in ("pattern_rewrite", "rename_symbol") and str(ti.get("dry_run", True)).lower() == "false":
                needs = [p for p in paths if check_target(core.resolve(p, cwd), ctx, role, "the code rewrite")]
                if needs:
                    require_approval(role, ctx, f"rewriting {', '.join(needs[:3])}")
            else:
                for p in paths:
                    check_secret(core.resolve(p, cwd), "the code tool")
        elif tool in ("shell", "execute_bash"):
            needs = check_shell(str(ti.get("command", "")), ctx, role, cwd)
            if needs:
                require_approval(role, ctx, "; ".join(list(dict.fromkeys(needs))[:3]))
        elif tool in ("read", "fs_read", "glob", "grep"):
            paths = tool_paths(ti, "read")
            if tool == "glob" and isinstance(ti.get("pattern"), str):
                pat = ti["pattern"]
                paths.append(pat if pat.startswith(("/", "~")) else os.path.join(str(ti.get("path") or cwd), pat))
            for p in paths:
                check_secret(core.resolve(p, cwd), f"the {tool} call")
        elif tool.startswith("@"):
            check_mcp(tool, role)
    except Refusal as r:
        refuse(role, ctx, tool, r, detail)
    except Exception as exc:  # A gate bug must be loud. The owner's ! shell skips hooks and can repair it.
        refuse(role, ctx, tool, Refusal("internal", f"the gate failed: {type(exc).__name__}: {exc}",
                                        f"The owner fixes {core.KIT}/lib/effortkit/gate.py, or reports it."), detail)
    sys.exit(0)


def context() -> None:
    try:
        payload = read_payload()
        ctx = core.resolve_context(INST, payload.get("cwd"), os.environ.get("EFFORTKIT_EFFORT"))
        out = [f"== effortkit context: instance {INST.name}, {core.now_utc()} =="]
        if ctx.error:
            out.append(f"Session problem: {ctx.error}")
        elif ctx.effort:
            e = ctx.effort
            out.append(f"Mode: supervisor of effort {e.name} (kind {e.kind}, branch {e.data.get('branch') or '-'}, "
                       f"tree {e.tree or 'none'}).")
            out.append(f"Plan folder: {e.plan}")
        else:
            out.append("Mode: home supervisor. You serve all efforts. Send tree work with `effort run`, never with the subagent tool.")
        if os.environ.get("EFFORTKIT_TERSE"):
            out.append("Style: the owner asked for terse replies in this session.")
        seen_file = INST.locks / f"context-{payload.get('session_id', 'none')}.json"
        last = (core.read_json(seen_file) or {}).get("last", 0)
        efforts = INST.efforts()
        if efforts:
            out.append(f"Open efforts ({len(efforts)}):")
            out.append(f"  {'effort':28} {'kind':8} {'stage':18} {'approval':9} runs")
        waiting, finished = [], []
        for e in efforts:
            runs = core.list_runs(e)
            states = [core.run_state(e, r["id"]) for r in runs]
            live = sum(1 for s, _ in states if s == "live")
            stage = e.stage()
            out.append(f"  {e.name:28} {e.kind:8} {stage:18} {e.approval()[0]:9} {live} live, {len(runs) - live} other")
            if stage in ("AWAITING_DECISION", "AWAITING_ANSWERS"):
                waiting.append(f"{e.name} ({stage})")
            elif (e.plan / "task.md").exists() and e.approval()[0] in ("none", "stale") and stage in ("PLANNING", "APPROVED"):
                waiting.append(f"{e.name} (plan approval: {e.approval()[1]})")
            for r, (s, code) in zip(runs, states):
                ef = core.runs_dir(e) / f"{r['id']}.exit"
                if s == "done" and ef.exists() and ef.stat().st_mtime > last:
                    finished.append(f"{e.name} {r['id']} exit {code}")
        if waiting:
            out.append("Waiting for the owner: " + "; ".join(waiting))
        if finished:
            out.append("Finished since your last prompt: " + "; ".join(finished[:8]))
        if ctx.effort and ctx.effort.related():
            rel = []
            for name in ctx.effort.related():
                other = INST.load_effort(name)
                rel.append(f"{name} ({other.stage()})" if other else name)
            out.append("Related: " + ", ".join(rel))
        inbox = len(list(INST.inbox.glob("*.md"))) if INST.inbox.is_dir() else 0
        if inbox:
            out.append(f"Knowledge inbox: {inbox} entries wait for a merge into the topic files.")
        pending = improve.pending_reports(INST)
        if pending:
            threshold = INST.config["improve"].get("threshold", 3)
            hint = " Propose `effort improve` to the owner." if len(pending) >= threshold else ""
            out.append(f"Workflow reports: {len(pending)} wait for triage.{hint}")
        stale = gen_stale()
        if stale:
            out.append(f"The generated agent configs are out of date ({stale}). Ask the owner to run `effort gen`.")
        print("\n".join(out))
        try:
            INST.locks.mkdir(parents=True, exist_ok=True)
            seen_file.write_text(json.dumps({"last": time.time()}), encoding="utf-8")
        except OSError:
            pass
    except Exception as exc:  # The context is a help. It never blocks a prompt.
        print(f"effortkit context hook error: {type(exc).__name__}: {exc}")
    sys.exit(0)


def gen_stale() -> str:
    try:
        from . import gen
    except ImportError:
        from effortkit import gen  # type: ignore
    return gen.stale_reason(INST)


def duties(role: str) -> None:
    spec = INST.roles.get(role, {})
    report_dir = INST.reports
    lines = [f"== Before you finish ({role}) ==",
             f"1. Artifact: write {spec.get('artifact', 'your result')} in the plan folder named in your brief.",
             "2. Findings about the project: one file per finding in findings/<UTC time>-<role>.md of the plan folder. "
             "List them under ## NEW ISSUES in your reply. Do not fix unrelated problems.",
             f"3. Workflow report: when the workflow slowed you down or misled you, write one file per problem in "
             f"{report_dir}/<UTC time>-<effort>-{role}.md, in the format of the contract. "
             "End your reply with ## IMPROVEMENT: <file names> or ## IMPROVEMENT: none.",
             f"4. A durable fact about the project goes into the knowledge inbox {INST.inbox}."]
    if INST.gated(role):
        help_ = INST.config["commit"]["subject_help"]
        lines.append(f'Commit the wave on the effort branch: git commit -m "{help_}". Never push.')
    lines.append("Reply to the supervisor tersely. Write the files in plain language.")
    print("\n".join(lines))
    sys.exit(0)


def main(argv: list[str]) -> None:
    global INST, INSTALL_TARGET
    if argv[:1] == ["--instance"] and len(argv) >= 2:
        try:
            INST = core.Instance(argv[1])
        except core.InstanceError as exc:
            if argv[2:3] == ["pre"]:
                print(f"REFUSED by the effortkit identity gate: {exc}", file=sys.stderr)
                sys.exit(2)
            print(f"effortkit: {exc}")
            sys.exit(0)
        argv = argv[2:]
    elif argv[:1] == ["--install-target"] and len(argv) >= 2:
        INSTALL_TARGET = real(argv[1])
        argv = argv[2:]
    elif argv[:1] == ["--install-target-env"]:
        # The installer config is fixed, and each installer session names its own target.
        t = os.environ.get("EFFORTKIT_INSTALL_TARGET")
        INSTALL_TARGET = real(t) if t else Path("/nonexistent/effortkit-install-target")
        argv = argv[1:]
    if len(argv) >= 2 and argv[0] == "pre" and (INST or INSTALL_TARGET):
        pre(argv[1])
    if argv[:1] == ["context"] and INST:
        context()
    if len(argv) >= 2 and argv[0] == "duties" and INST:
        duties(argv[1])
    print(__doc__, file=sys.stderr)
    sys.exit(2 if argv[:1] == ["pre"] else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
