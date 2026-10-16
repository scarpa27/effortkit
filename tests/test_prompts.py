"""Every command that a prompt or a skill names must run for the role that is told to run it.

A role that cannot run a command of its own prompt reports a refusal instead of the answer, and the owner does the
work by hand. In practice this was the most frequent defect of the workflow, so the check runs on every prompt.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.sandbox import GATE, FakeInstance, git_env
from effortkit import core, gen, skills

SPAN = re.compile(r"`([^`\n]+)`")
NOT_VERBS = {"a", "an", "the", "no", "not", "and", "or", "it", "one", "only", "every", "this", "that", "glob"}
SUB = {"effort": "e1", "name": "e1", "role": "developer", "file": "brief.md", "run-id": "20261023T000000Z-x-1",
       "ref": "origin/main", "base": "origin/main", "target": "origin/main", "source-branch": "feature", "kind": "code",
       "key": "TOY-1", "topic": "project", "text": "a fact", "words": "probe", "page": "/tmp/page.html",
       "short text": "ok", "tree": "TREE", "path": "tests", "url": "https://example.com/x.git", "dir": "/tmp/ek-dir",
       "folder": "/tmp/ek-dir", "UTC time": "20261023T000000Z", "the report file names": "x.md"}
# Spans that read as a command and that no role runs as written. Each entry has its reason.
NOT_RUN = {
    "git commit": "a template: the agent fills the subject. test_gate checks the commit rule itself",
    "effort approve": "the owner's command. The gate refuses it for every agent, and test_gate checks that",
    "effort gen": "the owner or the home supervisor runs it after a merge into the kit or the instance",
    "npx playwright install": "a setup step of the web-search MCP server, which the owner runs in the server folder",
    "npm run build": "a setup step of the web-search MCP server, which the owner runs in the server folder",
}
# The roles that run the commands of each kit skill.
SKILL_ROLES = {"lane-code": ("supervisor",), "lane-review": ("supervisor", "reviewer"), "lane-triage": ("supervisor",),
               "lane-kit": ("developer", "tester", "reviewer"), "lane-overlay": ("developer", "reviewer"),
               "plan-review": ("supervisor",)}


def fill(cmd: str) -> str:
    cmd = re.sub(r"<([^>]+)>", lambda m: SUB.get(m.group(1), "x"), cmd)
    return cmd.replace(" ...", "").replace("[", "").replace("]", "").strip()


def is_command(word: str) -> bool:
    return word not in NOT_VERBS and (word in ("effort", "effortkit") or bool(shutil.which(word)))


FENCE = re.compile(r"^[ \t]*```(?:bash|sh|shell)\n(.*?)^[ \t]*```", re.M | re.S)


def spans(text: str) -> list[str]:
    """Inline code spans that start with a program, and every line of a fenced bash block."""
    found = SPAN.findall(FENCE.sub("", text))
    for block in FENCE.findall(text):
        found += [re.sub(r"\s+#.*$", "", line) for line in block.splitlines() if line.strip()]
    out = []
    for s in found:
        s = s.strip()
        words = s.split()
        if s.startswith("!") or len(words) < 2 or not is_command(words[0]):
            continue
        out.append(fill(s))
    return out


def installer_part(text: str) -> str:
    """The installer runs the commands before <Finish>. The Finish section holds commands for the owner."""
    return text.split("<Finish>")[0]


def skipped(cmd: str) -> str | None:
    return next((why for prefix, why in NOT_RUN.items() if cmd.startswith(prefix)), None)


class PromptCommands(unittest.TestCase):
    def setUp(self):
        self.r = FakeInstance()
        self.inst = self.r.inst
        for name in ("e1", "k1", "o1"):
            self.r.approve(name)

    def tearDown(self):
        self.r.cleanup()

    def rows(self):
        v = gen.variables(self.inst)
        out = []
        for role in [core.SUPERVISOR, *self.inst.roles]:
            if (self.inst.profile(role) or {}).get("shell") is None:
                continue  # A role without a shell names commands for the plan. It runs none.
            for c in spans(gen.role_prompt(self.inst, role, v)):
                out.append((f"prompt {role}", (role,), c))
        for skill, roles in SKILL_ROLES.items():
            text = (core.KIT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            # Only the supervisor loads a lane skill. It passes each command to a role that can run it.
            out += [(skill, roles, c) for c in spans(text)]
        return out

    def cwd(self, role: str, source: str) -> Path:
        if role == core.SUPERVISOR:
            return self.r.root
        if source in ("lane-kit",) or role == "improver":
            return self.r.tree("k1")
        if source == "lane-overlay":
            return self.r.tree("o1")
        return self.r.tree("e1")

    def test_the_scan_finds_the_commands(self):
        cmds = {c for _, _, c in self.rows()}
        for needle in ("effort run e1 --role developer --brief brief.md --detach", "effort plan-review e1",
                       "python3 -m pytest tests", "python3 -m unittest discover -s tests -t ."):
            self.assertIn(needle, cmds)

    def refusal(self, role: str, source: str, raw: str) -> str:
        """Why the role cannot run the command, or an empty string when it can."""
        cmd = raw.replace("TREE", str(self.cwd(role, source)))
        shell = (self.inst.profile(role) or {}).get("shell")
        if shell in ("read", "read+tests"):
            pats = gen.shell_settings(self.inst, role, bool(self.inst.roles[role].get("web")))["allowedCommands"]
            if not any(re.search(p, cmd) for p in pats):
                return f"the allowlist of {role} refuses it"
        code, err = self.r.gate(role, "shell", {"command": cmd}, cwd=self.cwd(role, source))
        return f"the gate refuses it for {role}: {err.splitlines()[1] if err else code}" if code else ""

    def test_a_named_command_runs_for_its_role(self):
        problems = []
        for source, roles, raw in self.rows():
            if skipped(raw):
                continue
            reasons = [self.refusal(role, source, raw) for role in roles]
            if all(reasons):
                problems.append(f"{source}: `{raw}`: " + "; ".join(reasons))
        self.assertEqual(problems, [])

    def test_the_commands_of_shipped_skills_run_for_the_roles_that_load_them(self):
        r = FakeInstance({"mcp": {"researcher": ["@mcp-web-search"]}})
        try:
            for name in ("e1", "k1", "o1"):
                r.approve(name)
            inst, problems = r.inst, []
            loaders: dict[str, list[str]] = {}
            for role in [core.SUPERVISOR, *inst.roles]:
                for name in skills.for_role(inst, role):
                    loaders.setdefault(name, []).append(role)
            for name, folder in skills.kit_skills().items():
                if name in SKILL_ROLES:
                    continue  # A lane skill: the supervisor hands each command to a role. The other test covers it.
                for cmd in spans((folder / "SKILL.md").read_text(encoding="utf-8")):
                    if skipped(cmd):
                        continue
                    for role in loaders.get(name, []):
                        cwd = r.root if role == core.SUPERVISOR else r.tree("e1")
                        code, err = r.gate(role, "shell", {"command": cmd}, cwd=cwd)
                        if code:
                            problems.append(f"skill {name}: `{cmd}` for {role}: {err.splitlines()[1]}")
            self.assertEqual(problems, [])
        finally:
            r.cleanup()

    def test_the_skip_table_holds_no_stale_entry(self):
        cmds = [c for _, _, c in self.rows()]
        cmds += spans(installer_part((core.KIT / "agents/installer.md").read_text(encoding="utf-8")))
        for folder in skills.kit_skills().values():
            cmds += spans((folder / "SKILL.md").read_text(encoding="utf-8"))
        stale = [p for p in NOT_RUN if not any(c.startswith(p) for c in cmds)]
        self.assertEqual(stale, [])

    def test_the_installer_commands_pass_the_installer_gate(self):
        target = Path(tempfile.mkdtemp(prefix="ek-inst-target-"))
        try:
            env = {**git_env(Path(tempfile.gettempdir())), "EFFORTKIT_INSTALL_TARGET": str(target / "inst")}
            text = gen.render((core.KIT / "agents/installer.md").read_text(encoding="utf-8"),
                              {"kit": core.KIT, "python": sys.executable, "registry": core.registry_path()}, "installer")
            problems = []
            for cmd in spans(installer_part(text)):
                payload = {"cwd": str(core.KIT), "tool_name": "shell", "tool_input": {"command": cmd}, "session_id": "i"}
                p = subprocess.run([sys.executable, str(GATE), "--install-target-env", "pre", core.INSTALLER],
                                   input=json.dumps(payload), env=env, capture_output=True, text=True)
                if p.returncode != 0:
                    problems.append(f"`{cmd}`: {p.stderr.splitlines()[1] if p.stderr else p.returncode}")
            self.assertEqual(problems, [])
        finally:
            shutil.rmtree(target, ignore_errors=True)

    def test_every_artifact_of_a_role_is_writable_by_it(self):
        for role, spec in self.inst.roles.items():
            for name in re.findall(r"[\w.-]+\.md", spec.get("artifact", "")):
                code, err = self.r.gate(role, "write", {"command": "create", "path": str(self.r.plan("e1") / name),
                                                        "content": "x"}, cwd=self.r.tree("e1"))
                self.assertEqual(code, 0, f"{role} cannot write {name}: {err}")


if __name__ == "__main__":
    unittest.main()
