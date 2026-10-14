"""Generate the agent configs of an instance from the kit templates, the instance config and the overlay.

  <instance>/.kiro/agents/<role>.json and <role>.md   one config and one rendered prompt per role
  <instance>/.kiro/steering/*.md                      the rendered kit steering
  <instance>/.kiro/settings/cli.json                  the default agent and the configured settings
  <instance>/bin/effort                               the effort command of this instance
  <instance>/.kiro/gen.json                           what gen wrote, and the fingerprint of its inputs

Trust follows measurements of kiro-cli (docs/design.md): a headless stage needs trusted tools, a trusted tool ignores allowedPaths,
so the gate enforces the paths. Read-only roles get an untrusted shell with an anchored allowlist and
denyByDefault, which refuses other commands cleanly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

from . import allowlist as al
from . import core

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
GEN_FILE = "gen.json"
# The interpreter is fixed at generation time, so a session with another python3 first on PATH runs the same gate.
PYTHON = sys.executable


class GenError(Exception):
    pass


def render(text: str, variables: dict, source: str) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            raise GenError(f"{source}: unknown placeholder {{{{{key}}}}}")
        return str(variables[key])
    return PLACEHOLDER.sub(sub, text)


def bullets(items: list[str], empty: str) -> str:
    return "\n".join(f"- {i}" for i in items) if items else f"- {empty}"


def variables(inst: core.Instance) -> dict:
    cfg = inst.config
    roles = inst.roles
    tests = cfg["tests"].get("commands") or []
    return {
        "project": inst.name,
        "description": cfg.get("description") or f"the {inst.name} project",
        "instance": inst.root,
        "kit": core.KIT,
        "plan": inst.plan,
        "knowledge": inst.knowledge,
        "knowledge_inbox": inst.inbox,
        "reports": inst.reports,
        "reference": inst.reference,
        "trees": inst.trees,
        "overlay": inst.overlay,
        "contract": inst.kiro / "steering/workflow-contract.md",
        "commit_help": cfg["commit"]["subject_help"],
        "ticket_example": cfg["ticket"].get("example") or "none",
        "default_base": cfg["repo"].get("default_base") or "<ref>",
        "test_commands": bullets([f"`{t}`" for t in tests], "none configured. Ask the supervisor, and report the gap."),
        "roles_list": bullets([f"`{n}`: {s.get('description', '')}. Writes `{s.get('artifact', 'its artifact')}`."
                               for n, s in roles.items()], "none"),
        "kinds_list": bullets([f"`{n}`: {s.get('about', '')}. Lane skill `{s.get('lane', 'none')}`."
                               for n, s in inst.kinds.items()], "none"),
        "tester_globs": ", ".join(f"`{g}`" for g in inst.config["tester_globs"]),
    }


def role_prompt(inst: core.Instance, role: str, v: dict) -> str:
    kit_file = core.KIT / "agents" / f"{role}.md"
    overlay_file = inst.overlay / "agents" / f"{role}.md"
    parts = []
    builtin = role == core.SUPERVISOR or role in core.BUILTIN_ROLES
    if builtin:
        parts.append(render(kit_file.read_text(encoding="utf-8"), v, str(kit_file)))
    elif not overlay_file.is_file():
        raise GenError(f"custom role {role} needs its prompt in {overlay_file}")
    if overlay_file.is_file():
        text = render(overlay_file.read_text(encoding="utf-8"), v, str(overlay_file))
        parts.append(f"<Project rules for this role>\n{text.strip()}\n</Project rules for this role>" if builtin else text)
    if role != core.SUPERVISOR:
        footer = core.KIT / "agents/_footer.md"
        parts.append(render(footer.read_text(encoding="utf-8"), v, str(footer)))
    return "\n\n".join(p.strip() for p in parts) + "\n"


def gate_cmd(inst: core.Instance, *args: str) -> str:
    return shlex.join([PYTHON, str(core.KIT / "lib/effortkit/gate.py"), "--instance", str(inst.root), *args])


def has_files(folder: Path, pattern: str) -> bool:
    return folder.is_dir() and any(folder.glob(pattern))


def skill_uri(entry: str) -> str:
    return entry if "://" in entry else f"skill://{os.path.expanduser(entry)}"


def resources(inst: core.Instance, role: str) -> list[str]:
    out = [f"file://{inst.kiro}/steering/*.md"]
    if has_files(inst.overlay / "steering", "*.md"):
        out.append(f"file://{inst.overlay}/steering/*.md")
    if role == core.SUPERVISOR:
        out.append(f"skill://{core.KIT}/skills/**/SKILL.md")
    if has_files(inst.overlay / "skills", "**/SKILL.md"):
        out.append(f"skill://{inst.overlay}/skills/**/SKILL.md")
    spec = inst.roles.get(role, {})
    out += [skill_uri(s) for s in inst.config["extra_skills"].get(role, [])]
    out += [f"file://{inst.root / r}" if not r.startswith("/") and "://" not in r else r for r in spec.get("resources", [])]
    return out


def shell_settings(inst: core.Instance, role: str, web: bool) -> dict:
    families = [al.READ_ONLY, al.FORGE_READ, al.EFFORT_READ]
    if web:
        families.append(al.RESEARCH)
    if (inst.profile(role) or {}).get("shell") == "read+tests":
        families.append([al.segment(p) for p in inst.config["tests"].get("patterns") or []])
    return {"allowedCommands": al.allowlist(*[f for f in families if f]), "denyByDefault": True}


def agent_config(inst: core.Instance, role: str) -> dict:
    if role == core.SUPERVISOR:
        spec = {"description": f"{inst.name} supervisor - runs efforts, delegates every substantive task, keeps the plan "
                               "folders and the owner informed"}
        profile = core.PROFILES["supervisor"]
    else:
        spec = inst.roles[role]
        profile = inst.profile(role)
        if profile is None:
            raise GenError(f"role {role} has the unknown profile {spec.get('profile')!r}. Profiles: {', '.join(core.PROFILES)}")
    mcp = list(inst.config["mcp"].get(role, []))
    web = bool(spec.get("web"))
    settings: dict = {}
    if role == core.SUPERVISOR:
        tools = ["read", "write", "glob", "grep", "shell", "subagent", "todo", "thinking"]
        trusted = list(tools)
        team = [r for r in inst.roles]
        settings["subagent"] = {"availableAgents": team, "trustedAgents": team}
    elif profile["shell"] == "trusted":
        tools = ["read", "write", "glob", "grep", "code", "shell"]
        trusted = list(tools)
    elif profile["shell"] is None:
        tools = ["read", "write", "glob", "grep"]
        trusted = list(tools)
    else:
        tools = ["read", "write", "glob", "grep", "code", "shell"]
        trusted = ["read", "write", "glob", "grep", "code"]
        settings["shell"] = shell_settings(inst, role, web)
    if web:
        tools += ["web_search", "web_fetch"]
        trusted += ["web_search", "web_fetch"]
    tools += mcp
    trusted += mcp
    hooks: dict = {"preToolUse": [{"command": gate_cmd(inst, "pre", role)}]}
    if role == core.SUPERVISOR:
        hooks["userPromptSubmit"] = [{"command": gate_cmd(inst, "context")}]
    else:
        hooks["stop"] = [{"command": gate_cmd(inst, "duties", role)}]
    return {"name": role, "description": spec.get("description", role), "model": inst.model(role),
            "prompt": f"file://{inst.kiro}/agents/{role}.md", "tools": tools, "allowedTools": trusted,
            "resources": resources(inst, role), "toolsSettings": settings, "includeMcpJson": bool(mcp),
            "hooks": hooks}


def wrapper(inst: core.Instance) -> str:
    return ("#!/bin/sh\n"
            "# The effort command of this instance. effortkit generates it: edit instance.json, then run `effort gen`.\n"
            f"EFFORTKIT_INSTANCE={shlex.quote(str(inst.root))}\n"
            "export EFFORTKIT_INSTANCE\n"
            f"exec {shlex.quote(PYTHON)} {shlex.quote(str(core.KIT / 'bin/effort'))} \"$@\"\n")


def inputs(inst: core.Instance) -> list[Path]:
    kit = [core.KIT / "lib/effortkit" / f for f in ("gen.py", "core.py", "allowlist.py")]
    kit += sorted((core.KIT / "agents").glob("*.md")) + sorted((core.KIT / "steering").glob("*.md"))
    kit += sorted((core.KIT / "skills").glob("**/SKILL.md"))
    own = [inst.root / core.INSTANCE_FILE]
    for sub, pattern in (("agents", "*.md"), ("steering", "*.md"), ("skills", "**/SKILL.md")):
        own += sorted((inst.overlay / sub).glob(pattern)) if (inst.overlay / sub).is_dir() else []
    return kit + own


def fingerprint(inst: core.Instance) -> str:
    h = hashlib.sha256()
    for p in inputs(inst):
        h.update(str(p).encode() + b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    h.update(PYTHON.encode())
    return h.hexdigest()


def stale_reason(inst: core.Instance) -> str:
    rec = core.read_json(inst.kiro / GEN_FILE)
    if not rec:
        return "never generated"
    if rec.get("fingerprint") != fingerprint(inst):
        return "the kit, instance.json or the overlay changed since the last `effort gen`"
    return ""


def generate(inst: core.Instance) -> list[Path]:
    v = variables(inst)
    roles = [core.SUPERVISOR] + list(inst.roles)
    files: dict[Path, str] = {}
    for role in roles:
        files[inst.kiro / "agents" / f"{role}.md"] = role_prompt(inst, role, v)
        files[inst.kiro / "agents" / f"{role}.json"] = json.dumps(agent_config(inst, role), indent=2) + "\n"
    for src in sorted((core.KIT / "steering").glob("*.md")):
        files[inst.kiro / "steering" / src.name] = render(src.read_text(encoding="utf-8"), v, str(src))
    settings = core.merge({"chat.defaultAgent": core.SUPERVISOR}, inst.config.get("settings") or {})
    files[inst.kiro / "settings/cli.json"] = json.dumps(settings, indent=2) + "\n"
    files[inst.bin / "effort"] = wrapper(inst)
    old = core.read_json(inst.kiro / GEN_FILE) or {}
    for stale in set(old.get("files", [])) - {str(p) for p in files}:
        Path(stale).unlink(missing_ok=True)
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (inst.bin / "effort").chmod(0o755)
    core.write_json_once(inst.kiro / GEN_FILE, {"generated": core.now_utc(), "fingerprint": fingerprint(inst),
                                                "kit": str(core.KIT), "files": sorted(str(p) for p in files)})
    return sorted(files)


# ---------------------------------------------------------------- the installer, which belongs to the kit

def installer_config() -> dict:
    gate = shlex.join([PYTHON, str(core.KIT / "lib/effortkit/gate.py"), "--install-target-env", "pre", core.INSTALLER])
    read_only = al.allowlist(al.READ_ONLY, al.FORGE_READ, [rf"(?:{al.PLAIN}*/)?effortkit +(?:help|instances|--help|check|mcp-servers){al.ARGS}"])
    return {"name": core.INSTALLER, "description": "Sets up effortkit for a new project in an interactive interview",
            "model": core.DEFAULTS["models"]["default"], "prompt": f"file://{core.KIT}/.kiro/agents/installer.md",
            "tools": ["read", "write", "glob", "grep", "code", "shell", "thinking"],
            "allowedTools": ["read", "write", "glob", "grep", "code", "thinking"],
            "resources": [f"file://{core.KIT}/README.md", f"file://{core.KIT}/docs/config.md"],
            # No denyByDefault: a command outside the list asks the owner, who sits at the terminal.
            "toolsSettings": {"shell": {"allowedCommands": read_only}},
            "includeMcpJson": False, "hooks": {"preToolUse": [{"command": gate}]}}


def generate_kit() -> list[Path]:
    v = {"kit": core.KIT, "python": PYTHON, "registry": core.registry_path()}
    src = core.KIT / "agents/installer.md"
    files = {core.KIT / ".kiro/agents/installer.md": render(src.read_text(encoding="utf-8"), v, str(src)),
             core.KIT / ".kiro/agents/installer.json": json.dumps(installer_config(), indent=2) + "\n"}
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return sorted(files)
