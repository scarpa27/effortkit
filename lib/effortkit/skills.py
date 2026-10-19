"""The skills that agents use: which the kit ships, which role gets which, and their workspace copies.

Every skill that an agent loads comes from the kit or from the overlay of its instance, never from the machine.
`effort gen` copies each of them into <instance>/.kiro/skills/<name>/, and the agent configs name only those copies.
So an instance works the same on every machine, and a change in ~/.kiro/skills cannot change a running workflow.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import core

LOCK_NAME = "skills-lock.json"

# The skills of the built-in roles. Every role also gets the overlay skills of its instance, and the supervisor gets
# the lane skill of every kind.
ROLE_SKILLS = {
    core.SUPERVISOR: ["plan-review", "lavish", "grill-me", "caveman", "asd-ste100", "engineering-writeup",
                      "diagnostic-experiment-matrix"],
    "explorer": ["caveman", "asd-ste100"],
    "researcher": ["caveman", "asd-ste100", "web-search"],
    "planner": ["caveman", "asd-ste100"],
    "developer": ["caveman", "asd-ste100"],
    "tester": ["caveman", "asd-ste100"],
    "reviewer": ["caveman", "asd-ste100"],
    "debugger": ["caveman", "asd-ste100", "diagnostic-experiment-matrix"],
    "improver": ["caveman", "asd-ste100"],
}
# A custom role replies to the supervisor like every specialist, so it gets these unless the config says otherwise.
CUSTOM_ROLE_SKILLS = ["caveman", "asd-ste100"]
INSTALLER_SKILLS = ["grill-me", "lavish"]
# A skill that names another skill as its next step needs that skill too, or the agent follows a dead reference.
COMPANIONS = {"caveman": ["ultracave", "megacave"], "grill-me": ["grilling"]}


class SkillError(Exception):
    pass


def folder_hash(path: Path) -> str:
    """sha256 over the relative path and the bytes of every file, in path order."""
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(f.relative_to(path).as_posix().encode() + b"\0")
        h.update(f.read_bytes() + b"\0")
    return h.hexdigest()


def lock(kit: Path = core.KIT) -> dict:
    path = kit / "skills" / LOCK_NAME
    data = core.read_json(path)
    if not data or not isinstance(data.get("skills"), dict):
        raise SkillError(f"{path} is missing or has no skills")
    return data["skills"]


def kit_skills(kit: Path = core.KIT) -> dict[str, Path]:
    return {p.parent.name: p.parent for p in sorted((kit / "skills").glob("*/SKILL.md"))}


def overlay_skills(inst: core.Instance) -> dict[str, Path]:
    folder = inst.overlay / "skills"
    return {p.parent.name: p.parent for p in sorted(folder.glob("*/SKILL.md"))} if folder.is_dir() else {}


def sources(inst: core.Instance) -> dict[str, Path]:
    """Every skill that the instance can use. An overlay skill replaces the kit skill of the same name."""
    return {**kit_skills(), **overlay_skills(inst)}


def role_tools(inst: core.Instance, role: str) -> set[str]:
    return set(inst.config["mcp"].get(role, []))


def wanted(inst: core.Instance, role: str) -> list[str]:
    """The skill names that a role asks for, before the checks: defaults, lanes, config, companions, overlay."""
    spec = inst.roles.get(role, {})
    if role == core.SUPERVISOR or role in core.BUILTIN_ROLES:
        names = list(ROLE_SKILLS.get(role, []))
    else:
        names = list(spec.get("skills", CUSTOM_ROLE_SKILLS))
    if role == core.SUPERVISOR:
        names += [k["lane"] for k in inst.kinds.values() if k.get("lane")]
    names += inst.config["skills"].get(role, [])
    # An overlay skill goes to every role, unless the config names it for some roles. Then only those roles get it.
    named = {n for listed in inst.config["skills"].values() for n in listed}
    names += [n for n in overlay_skills(inst) if n not in named]
    out: list[str] = []
    for n in names:
        for m in [n, *COMPANIONS.get(n, [])]:
            if m not in out:
                out.append(m)
    return out


def for_role(inst: core.Instance, role: str) -> list[str]:
    """The skills that a role loads. A skill that needs a tool goes only to a role that has the tool."""
    entries = lock()
    off = set(inst.config.get("skills_off") or [])
    out = []
    for name in wanted(inst, role):
        if name in off:
            continue
        needs = set(entries.get(name, {}).get("requires_tools", []))
        if needs and not needs <= role_tools(inst, role):
            continue
        out.append(name)
    return out


def installed(inst: core.Instance) -> dict[str, Path]:
    """The source folder of every skill that some role of the instance loads."""
    src = sources(inst)
    names: list[str] = []
    for role in [core.SUPERVISOR, *inst.roles]:
        names += [n for n in for_role(inst, role) if n not in names]
    missing = [n for n in names if n not in src]
    if missing:
        raise SkillError(f"no skill named {', '.join(missing)} in {core.KIT / 'skills'} or {inst.overlay / 'skills'}")
    return {n: src[n] for n in names}


def copies(chosen: dict[str, Path], dest: Path) -> dict[Path, bytes]:
    """The files of the workspace copies: dest/<name>/<file> for every file of every chosen skill."""
    out = {}
    for name, folder in chosen.items():
        for f in sorted(p for p in folder.rglob("*") if p.is_file()):
            out[dest / name / f.relative_to(folder)] = f.read_bytes()
    return out


def problems(inst: core.Instance | None = None, kit: Path = core.KIT) -> list[str]:
    """What is wrong with the shipped skills, and with the skill config of an instance."""
    out = []
    try:
        entries = lock(kit)
    except SkillError as exc:
        return [str(exc)]
    shipped = kit_skills(kit)
    for name in sorted(set(shipped) - set(entries)):
        out.append(f"skill {name} ships without an entry in {LOCK_NAME}")
    for name in sorted(set(entries) - set(shipped)):
        out.append(f"{LOCK_NAME} names the skill {name}, which the kit does not ship")
    for name, entry in sorted(entries.items()):
        if name not in shipped or entry.get("source") == "effortkit":
            continue
        for key in ("source", "license"):
            if not entry.get(key):
                out.append(f"skill {name}: the lock entry needs a {key}")
        if entry.get("sha256") != folder_hash(shipped[name]):
            out.append(f"skill {name}: the files differ from the lock. Record the change, then run `effortkit skills lock`")
    names = set(shipped)
    for role, wanted_names in ROLE_SKILLS.items():
        out += [f"role {role}: the kit skill {n} does not exist" for n in wanted_names if n not in names]
    out += [f"{n}: the companion {m} does not exist" for n, ms in COMPANIONS.items() for m in ms if m not in names]
    if inst is not None:
        known = set(sources(inst))
        for role, extra in (inst.config.get("skills") or {}).items():
            if role != core.SUPERVISOR and role not in inst.roles:
                out.append(f"skills.{role}: no role of that name")
            out += [f"skills.{role}: no skill named {n} in the kit or in overlay/skills" for n in extra if n not in known]
        out += [f"skills_off: no skill named {n}" for n in inst.config.get("skills_off") or [] if n not in known]
        for name, spec in inst.roles.items():
            out += [f"role {name}: no skill named {n}" for n in spec.get("skills", []) if n not in known]
    return out


def relock(kit: Path = core.KIT) -> list[str]:
    """Write the current hash of every vendored skill into the lock. Return the names that changed."""
    path = kit / "skills" / LOCK_NAME
    data = core.read_json(path) or {"version": 1, "skills": {}}
    changed = []
    for name, folder in kit_skills(kit).items():
        entry = data["skills"].get(name)
        if entry is None or entry.get("source") == "effortkit":
            continue
        digest = folder_hash(folder)
        if entry.get("sha256") != digest:
            entry["sha256"] = digest
            changed.append(name)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed
