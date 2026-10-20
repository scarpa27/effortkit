"""effortkit - the kit command.

  effortkit installer [<dir>]        the interactive installer agent for a new project; it writes only in <dir>
  effortkit init <url-or-path> [--name N] [--out answers.json]   detect the answers of a new instance, with evidence
  effortkit install --dir <dir> [--config <answers.json>] [--name N] [--repo-url U | --repo-path P] [--base REF]
                                     create an instance without the agent, from answers
  effortkit install --dir <dir> --repair   restore the layout, the hooks and the generated files of an instance
  effortkit check <dir> [--validate] check the config and the overlay of an instance, or of an overlay tree
  effortkit instances                the registered instances, with their open efforts and reports
  effortkit reports [--scope kit]    the open workflow reports of every registered instance
  effortkit mcp-servers              the MCP server names for mcp.<role>, without their settings, which hold tokens
  effortkit skills [lock [--kit DIR]] the skills that the kit ships, their sources and licences; lock records the hashes
  effortkit selftest                 run the kit tests
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import core, detect, gen, improve, install, skills


def die(msg: str, code: int = 2) -> None:
    print(f"effortkit: {msg}", file=sys.stderr)
    sys.exit(code)


def cmd_init(a) -> None:
    try:
        answers = detect.detect(a.source, a.name)
    except RuntimeError as exc:
        die(str(exc))
    text = json.dumps(answers, indent=2) + "\n"
    for key, why in answers["_evidence"].items():
        print(f"  {key}: {why}", file=sys.stderr)
    if a.out:
        Path(a.out).expanduser().write_text(text, encoding="utf-8")
        print(f"wrote {a.out}. Review it, then: effortkit install --dir <dir> --config {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def cmd_install(a) -> None:
    target = Path(a.dir).expanduser()
    if a.repair:
        try:
            inst = install.repair(target)
        except (install.InstallError, core.InstanceError, gen.GenError) as exc:
            die(str(exc))
        print(f"repaired instance {inst.name} in {inst.root}")
        return
    answers: dict = {}
    if a.config:
        try:
            answers = json.loads(Path(a.config).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            die(f"cannot read the answers {a.config}: {exc}")
    if a.name:
        answers["name"] = a.name
    repo = answers.setdefault("repo", {})
    if a.repo_url:
        repo["url"] = a.repo_url
    if a.repo_path:
        repo["path"] = a.repo_path
    if a.base:
        repo["default_base"] = a.base
    try:
        inst = install.install(target, answers, clone=not a.no_clone)
    except (install.InstallError, core.InstanceError, gen.GenError) as exc:
        die(str(exc))
    print(f"instance {inst.name} created in {inst.root}")
    print(f"  project       {inst.product}")
    print(f"  config        {inst.root / core.INSTANCE_FILE}")
    print(f"  overlay       {inst.overlay}")
    print(f"  start         {inst.bin / 'effort'} home")
    print(f"  on PATH       ln -s {inst.bin / 'effort'} ~/.local/bin/{inst.name}-effort   (optional, pick any free name)")


def cmd_installer(a) -> None:
    target = core.real(Path(a.dir).expanduser()) if a.dir else None
    gen.generate_kit()
    env = dict(os.environ)
    env.pop("EFFORTKIT_INSTANCE", None)
    env.pop("EFFORTKIT_EFFORT", None)
    if target:
        env["EFFORTKIT_INSTALL_TARGET"] = str(target)
    env["PATH"] = f"{core.KIT / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["EFFORTKIT_MACHINE_KIRO_HOME"] = str(gen.machine_kiro_home())
    env["KIRO_HOME"] = str(core.KIT / gen.KIRO_HOME_DIR)
    os.chdir(core.KIT)
    first = (f"Set up effortkit for a new project. The instance goes into {target}." if target
             else "Set up effortkit for a new project. Ask me where the instance must live.")
    os.execvpe("kiro-cli", ["kiro-cli", "chat", "--agent", core.INSTALLER, first], env)


def cmd_check(a) -> None:
    root = core.real(Path(a.dir).expanduser())
    errors = install.check_config(root)
    for e in errors:
        print(f"FAIL {e}")
    if not errors and a.validate:
        try:
            inst = core.Instance(root)
        except core.InstanceError as exc:
            die(str(exc))
        problems = install.validate_with_kiro(inst)
        for p in problems:
            print(f"FAIL kiro-cli: {p}")
        errors += problems
    if not errors:
        print(f"ok   {root / core.INSTANCE_FILE}: the config loads, and every prompt and agent config renders")
    sys.exit(1 if errors else 0)


def cmd_instances(a) -> None:
    roots = core.registered_instances()
    if not roots:
        print("no instances registered. Create one with: effortkit installer <dir>")
        return
    print(f"{'instance':24} {'efforts':>7} {'reports':>7}  root")
    for r in roots:
        try:
            inst = core.Instance(r)
        except core.InstanceError:
            print(f"{'?':24} {'-':>7} {'-':>7}  {r} (missing or broken)")
            continue
        print(f"{inst.name:24} {len(inst.efforts()):7} {len(improve.pending_reports(inst)):7}  {inst.root}")


def cmd_reports(a) -> None:
    found = 0
    for r in core.registered_instances():
        try:
            inst = core.Instance(r)
        except core.InstanceError:
            continue
        for rep in improve.pending_reports(inst):
            if a.scope and rep.scope != a.scope:
                continue
            found += 1
            print(f"{inst.name:20} {rep.scope:8} {rep.severity:9} {rep.area:18} {rep.path}")
    if not found:
        print("no open workflow reports" + (f" with scope {a.scope}" if a.scope else ""))


def cmd_mcp_servers(a) -> None:
    """The MCP server names that a role may list in mcp.<role>. The settings stay unread, because they hold tokens."""
    names = []
    for path in (core.HOME / ".kiro/settings/mcp.json", Path.cwd() / ".kiro/settings/mcp.json"):
        data = core.read_json(path) or {}
        names += [n for n in (data.get("mcpServers") or {}) if n not in names]
    print("\n".join(f"@{n}" for n in names) if names else "no MCP servers are configured")


def cmd_skills(a) -> None:
    kit = core.real(Path(a.kit).expanduser()) if a.kit else core.KIT
    if a.action == "lock":
        changed = skills.relock(kit)
        print(f"recorded new hashes for: {', '.join(changed)}" if changed else "every hash was current")
        return
    if a.action:
        die(f"unknown skills action '{a.action}'. Use `effortkit skills` or `effortkit skills lock`.")
    entries = skills.lock(kit)
    users = {}
    for role, names in skills.ROLE_SKILLS.items():
        for n in names:
            users.setdefault(n, []).append(role)
    for n, roles in users.items():
        if len(roles) == len(skills.ROLE_SKILLS):
            users[n] = ["every role"]
    print(f"{'skill':16} {'licence':12} {'roles':38} source")
    for name in skills.kit_skills(kit):
        e = entries.get(name, {})
        roles = ", ".join(users.get(name, [])) or ("supervisor (lane)" if name.startswith("lane-") else
                                                   "with its parent skill" if any(name in v for v in skills.COMPANIONS.values()) else "-")
        ref = e.get("ref") or (e.get("commit") or "")[:12]
        print(f"{name:16} {e.get('license', 'the kit') [:12]:12} {roles[:38]:38} {e.get('source', '?')} {ref}".rstrip())
    for p in skills.problems(kit=kit):
        print(f"FAIL {p}")


def cmd_selftest(a) -> None:
    sys.exit(subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=core.KIT).returncode)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="effortkit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("init"); p.add_argument("source"); p.add_argument("--name"); p.add_argument("--out")
    p.set_defaults(fn=cmd_init)
    p = sp.add_parser("install"); p.add_argument("--dir", required=True); p.add_argument("--config")
    p.add_argument("--name"); p.add_argument("--repo-url"); p.add_argument("--repo-path"); p.add_argument("--base")
    p.add_argument("--no-clone", action="store_true"); p.add_argument("--repair", action="store_true")
    p.set_defaults(fn=cmd_install)
    p = sp.add_parser("installer"); p.add_argument("dir", nargs="?"); p.set_defaults(fn=cmd_installer)
    p = sp.add_parser("check"); p.add_argument("dir"); p.add_argument("--validate", action="store_true"); p.set_defaults(fn=cmd_check)
    p = sp.add_parser("instances"); p.set_defaults(fn=cmd_instances)
    p = sp.add_parser("reports"); p.add_argument("--scope", choices=improve.SCOPES); p.set_defaults(fn=cmd_reports)
    p = sp.add_parser("mcp-servers"); p.set_defaults(fn=cmd_mcp_servers)
    p = sp.add_parser("skills"); p.add_argument("action", nargs="?", default=""); p.add_argument("--kit")
    p.set_defaults(fn=cmd_skills)
    p = sp.add_parser("selftest"); p.set_defaults(fn=cmd_selftest)
    p = sp.add_parser("help"); p.set_defaults(fn=lambda a: ap.print_help())
    args = ap.parse_args(argv or ["help"])
    args.fn(args)
