"""The inbox of an instance: one note per file, from the agents and the owner, routed by its type line.

  type: fact       a durable fact about the project. The supervisor merges it into a knowledge topic at effort close.
  type: workflow   a problem that the workflow caused. The improver triages it in an improvement round.

One folder and one format keep the end-of-stage duties short: an agent writes notes, and the type decides who reads.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import core

TYPES = ("fact", "workflow")
HEADER = re.compile(r"^([a-z][a-z-]*)\s*:\s*(.*)$")
STAMP = re.compile(r"^(\d{8}T\d{6}Z)(?:-\d+)?-(.+)\.md$")


@dataclass
class Note:
    path: Path
    type: str
    created: str
    effort: str
    role: str
    title: str
    head: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name


def split_name(inst: core.Instance, name: str) -> tuple[str, str, str]:
    """(created, effort, role) from <UTC stamp>-<effort>-<role>.md. Role names hold dashes, so known roles go first."""
    m = STAMP.match(name)
    if not m:
        return "", "", ""
    rest = m.group(2)
    roles = sorted(set(inst.roles) | {core.SUPERVISOR, core.INSTALLER, "owner"}, key=len, reverse=True)
    for role in roles:
        if rest.endswith("-" + role):
            return m.group(1), rest[:-len(role) - 1], role
    return m.group(1), rest, ""


def parse(inst: core.Instance, path: Path) -> Note:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    head: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if head:
                break
            continue
        m = HEADER.match(line.strip())
        if not m or line.startswith("#"):
            break
        head[m.group(1).lower()] = m.group(2).strip()
    kind = head.get("type", "").lower()
    if kind not in TYPES:
        # An agent that forgot the type line still wrote one of the two formats.
        kind = "fact" if "topic" in head or "target" in head else "workflow" if {"scope", "severity"} & set(head) else "unknown"
    title = head.get("title") or next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), "")
    created, effort, role = split_name(inst, path.name)
    return Note(path=path, type=kind, created=created, effort=head.get("effort") or effort,
                role=head.get("role") or role, title=title, head=head)


def notes(inst: core.Instance, kind: str | None = None) -> list[Note]:
    if not inst.inbox.is_dir():
        return []
    found = [parse(inst, p) for p in sorted(inst.inbox.glob("*.md"))]
    return [n for n in found if kind is None or n.type == kind]


def facts_of(inst: core.Instance, effort: str) -> list[Note]:
    return [n for n in notes(inst, "fact") if n.effort == effort]


def write(inst: core.Instance, kind: str, head: dict[str, str], body: str, effort: str = "home",
          role: str = "owner") -> Path:
    if kind not in TYPES:
        raise ValueError(f"a note has the type fact or workflow, not {kind!r}")
    inst.inbox.mkdir(parents=True, exist_ok=True)
    path, n = inst.inbox / f"{core.stamp()}-{effort}-{role}.md", 1
    while path.exists():
        path, n = inst.inbox / f"{core.stamp()}-{n}-{effort}-{role}.md", n + 1
    lines = [f"type: {kind}", *(f"{k}: {v}" for k, v in head.items()), f"effort: {effort}", f"role: {role}"]
    path.write_text("\n".join(lines) + "\n\n" + body.strip() + "\n", encoding="utf-8")
    return path
