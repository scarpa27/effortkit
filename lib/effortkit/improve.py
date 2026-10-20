"""Workflow reports: what the agents say would make the workflow better, and what the gates and runs show.

An agent writes one note of type workflow per problem into the inbox. The improver triages them in an effort of kind
kit or overlay and writes its decision per note into triage.md. `effort close` then moves each decided note to
done/<effort>/ and appends one ledger line, so the inbox holds only open notes.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import core, inbox

SCOPES = ("kit", "overlay", "unsure")
SEVERITIES = ("blocker", "friction", "idea")
DECISIONS = ("accepted", "rejected", "deferred", "merged", "done")
# A triage line: "- <note file>: <decision> - <reason>". The reason is optional.
TRIAGE = re.compile(r"^\s*[-*]\s+`?([\w.-]+\.md)`?\s*:\s*(" + "|".join(DECISIONS) + r")\b\s*[-:]*\s*(.*)$", re.I)


@dataclass
class Report:
    path: Path
    scope: str
    area: str
    severity: str
    effort: str
    role: str
    created: str
    title: str

    @property
    def name(self) -> str:
        return self.path.name


def as_report(note: inbox.Note) -> Report:
    scope = note.head.get("scope", "unsure").lower()
    severity = note.head.get("severity", "friction").lower()
    return Report(path=note.path, scope=scope if scope in SCOPES else "unsure", area=note.head.get("area", "other"),
                  severity=severity if severity in SEVERITIES else "friction", effort=note.effort, role=note.role,
                  created=note.created, title=note.title)


def parse_report(inst: core.Instance, path: Path) -> Report:
    return as_report(inbox.parse(inst, path))


def pending_reports(inst: core.Instance) -> list[Report]:
    return [as_report(n) for n in inbox.notes(inst, "workflow")]


def write_report(inst: core.Instance, text: str, scope: str = "unsure", area: str = "other",
                 severity: str = "friction", effort: str = "home", role: str = "owner") -> Path:
    return inbox.write(inst, "workflow", {"scope": scope, "area": area, "severity": severity},
                       f"## What happened\n{text.strip()}", effort, role)


# ---------------------------------------------------------------- signals that need no agent

STATE = "state.json"


def state(inst: core.Instance) -> dict:
    return core.read_json(inst.improvements / STATE) or {}


def save_state(inst: core.Instance, data: dict) -> None:
    core.write_json_once(inst.improvements / STATE, data)


def _norm(reason: str) -> str:
    reason = re.sub(r"(/[\w.@+-]+)+/?", "<path>", reason)
    reason = re.sub(r"'[^']*'|\"[^\"]*\"", "<text>", reason)
    return re.sub(r"\d+", "N", reason)[:160]


def gate_logs(inst: core.Instance) -> list[Path]:
    logs = [inst.locks / "gate-home.log"]
    if inst.plan.is_dir():
        logs += sorted(inst.plan.glob("*/scratch/gate.log"))
    return [p for p in logs if p.is_file()]


def signals(inst: core.Instance, since: str = "") -> dict:
    """Refusals of the gates and failed runs after `since` (a UTC time stamp). They show friction that no agent reported."""
    refusals: Counter = Counter()
    examples: dict = {}
    for log in gate_logs(inst):
        effort = log.parent.parent.name if log.name == "gate.log" else "home"
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("decision") != "refuse" or rec.get("time", "") <= since:
                continue
            key = (rec.get("gate", "?"), rec.get("role", "?"), _norm(rec.get("reason", "")))
            refusals[key] += 1
            examples.setdefault(key, (effort, rec.get("call", "")[:200]))
    failed = []
    for e in inst.efforts(include_closed=True):
        for r in core.list_runs(e):
            if r.get("created", "") <= since:
                continue
            st, code = core.run_state(e, r["id"])
            if (st == "done" and code not in (0, None)) or st == "lost":
                failed.append({"effort": e.name, "run": r["id"], "role": r.get("role"), "state": st, "exit": code})
    return {"since": since, "refusals": [{"gate": k[0], "role": k[1], "reason": k[2], "count": n,
                                          "effort": examples[k][0], "example": examples[k][1]}
                                         for k, n in refusals.most_common()],
            "failed_runs": failed}


def signals_markdown(sig: dict) -> str:
    out = [f"# Signals since {sig['since'] or 'the start'}", "",
           "The gates and the runs recorded these. No agent wrote them, so they show friction that nobody reported.", ""]
    out.append("## Gate refusals")
    if not sig["refusals"]:
        out.append("- none")
    for r in sig["refusals"]:
        out.append(f"- {r['count']}x gate {r['gate']}, role {r['role']}: {r['reason']}")
        out.append(f"  - first in effort {r['effort']}: `{r['example']}`")
    out += ["", "## Failed or lost runs (exit 124 is the run time limit)"]
    if not sig["failed_runs"]:
        out.append("- none")
    for f in sig["failed_runs"]:
        out.append(f"- {f['effort']} {f['run']} ({f['role']}): {f['state']}, exit {f['exit']}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- triage and the ledger

def triage_decisions(plan: Path) -> list[tuple[str, str, str]]:
    try:
        text = (plan / "triage.md").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        m = TRIAGE.match(line)
        if m:
            out.append((m.group(1), m.group(2).lower(), m.group(3).strip()))
    return out


def settle(inst: core.Instance, e: core.Effort) -> list[str]:
    """Move the reports that triage.md decided into done/<effort>/ and append them to the ledger. Return a summary."""
    decided = triage_decisions(e.plan)
    if not decided:
        return []
    done_dir = inst.reports_done / e.name
    summary = []
    with open(inst.ledger, "a", encoding="utf-8") as ledger:
        for name, decision, reason in decided:
            src = inst.inbox / name
            if decision == "deferred" or not src.is_file():
                summary.append(f"{name}: {decision}{'' if src.is_file() else ' (not in the inbox)'}")
                continue
            rep = parse_report(inst, src)
            done_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), done_dir / name)
            ledger.write(json.dumps({"report": name, "decision": decision, "reason": reason, "effort": e.name,
                                     "kind": e.kind, "scope": rep.scope, "area": rep.area, "severity": rep.severity,
                                     "from_effort": rep.effort, "from_role": rep.role, "settled": core.now_utc()}) + "\n")
            summary.append(f"{name}: {decision}")
    return summary


def ledger(inst: core.Instance) -> list[dict]:
    try:
        lines = inst.ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def stats(inst: core.Instance) -> str:
    """Reports per finished effort, oldest first. The trend shows whether the workflow fits the project better."""
    per_effort: dict[str, Counter] = defaultdict(Counter)
    for rec in ledger(inst):
        per_effort[rec.get("from_effort") or "?"][rec.get("severity", "friction")] += 1
    for rep in pending_reports(inst):
        per_effort[rep.effort or "?"][rep.severity] += 1
    created = {}
    for e in inst.efforts(include_closed=True):
        created[e.name] = e.data.get("created", "")
    rows = sorted(per_effort.items(), key=lambda kv: created.get(kv[0], "~"))
    out = [f"{'effort':32} {'created':20} {'blocker':>7} {'friction':>8} {'idea':>5}"]
    for name, c in rows:
        out.append(f"{name:32} {created.get(name, '-')[:19]:20} {c['blocker']:7} {c['friction']:8} {c['idea']:5}")
    decided = Counter(rec.get("decision") for rec in ledger(inst))
    out.append("")
    out.append(f"open: {len(pending_reports(inst))}; settled: " + ", ".join(f"{k} {v}" for k, v in sorted(decided.items()))
               if decided else f"open: {len(pending_reports(inst))}; settled: none")
    return "\n".join(out)
