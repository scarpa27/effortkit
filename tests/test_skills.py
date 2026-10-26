"""Every skill that an agent loads ships with the kit, and each instance loads only its own workspace copies."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.sandbox import CONFIG, FakeInstance, RealInstance, sh
from effortkit import core, gen, install, skills

# The skills that the agents of the workflow load, by name. Each of them must ship with the kit.
WORKFLOW_SKILLS = {"lavish", "caveman", "asd-ste100", "grill-me", "web-search", "plan-review"}
# Generic skills of the owner that the kit ships too.
OWNER_SKILLS = {"diagnostic-experiment-matrix", "engineering-writeup"}


def private_terms() -> list[str]:
    """Names that no tracked file may hold: of a company, of a project, of a machine. One regex per line.

    The list stays outside the repository, because a list of the names would itself mention them.
    """
    path = core.config_home() / "private-terms"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


class ShippedSkills(unittest.TestCase):
    def test_the_lock_matches_the_shipped_folders(self):
        self.assertEqual(skills.problems(), [])

    def test_the_skills_of_the_workflow_ship_with_their_companions(self):
        shipped = set(skills.kit_skills())
        self.assertLessEqual(WORKFLOW_SKILLS | OWNER_SKILLS, shipped)
        for name, companions in skills.COMPANIONS.items():
            self.assertLessEqual(set(companions), shipped, name)

    def test_every_vendored_skill_carries_its_licence(self):
        for name, entry in skills.lock().items():
            if entry.get("source") in ("effortkit", "owner"):
                continue
            self.assertTrue((skills.kit_skills()[name] / "LICENSE").is_file(), name)

    def test_a_changed_vendored_file_is_named(self):
        kit = Path(tempfile.mkdtemp(prefix="ek-kit-"))
        try:
            shutil.copytree(core.KIT / "skills", kit / "skills")
            self.assertEqual(skills.problems(kit=kit), [])
            (kit / "skills/lavish/SKILL.md").write_text("changed\n")
            self.assertIn("skill lavish: the files differ from the lock", " ".join(skills.problems(kit=kit)))
            self.assertEqual(skills.relock(kit), ["lavish"])
            self.assertEqual(skills.problems(kit=kit), [])
        finally:
            shutil.rmtree(kit, ignore_errors=True)

    def test_the_owner_skills_record_the_permission(self):
        for name, entry in skills.lock().items():
            if entry.get("source") == "owner":
                self.assertIn("The owner allowed it in the kit on", entry["license"], name)
                self.assertTrue(entry.get("origin"), name)

    def test_no_tracked_file_holds_a_private_term(self):
        import re
        terms = private_terms()
        if not terms:
            self.skipTest(f"no private terms in {core.config_home() / 'private-terms'}")
        rule = re.compile("|".join(f"(?:{x})" for x in terms), re.I)
        files = subprocess.run(["git", "ls-files"], cwd=core.KIT, capture_output=True, text=True).stdout.split()
        hits = []
        for name in files:
            text = (core.KIT / name).read_text(encoding="utf-8", errors="replace")
            hits += [f"{name}: {m.group(0)}" for m in rule.finditer(text)]
        self.assertEqual(hits, [])

    def test_no_shipped_skill_names_a_path_of_this_machine(self):
        home = str(Path.home())
        for f in (core.KIT / "skills").rglob("*"):
            if f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn(home, text, f)
                self.assertNotIn(os.environ.get("USER", "nobody-at-all"), text, f)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.r = FakeInstance()

    def tearDown(self):
        self.r.cleanup()

    def test_roles_and_their_skills(self):
        inst = self.r.inst
        sup = skills.for_role(inst, core.SUPERVISOR)
        for name in ("plan-review", "lavish", "grill-me", "grilling", "caveman", "ultracave", "megacave",
                     "engineering-writeup", "diagnostic-experiment-matrix",
                     "lane-code", "lane-review", "lane-triage", "lane-kit", "lane-overlay"):
            self.assertIn(name, sup)
        self.assertIn("diagnostic-experiment-matrix", skills.for_role(inst, "debugger"))
        for role in core.BUILTIN_ROLES:
            self.assertIn("caveman", skills.for_role(inst, role), role)
            self.assertNotIn("lavish", skills.for_role(inst, role), role)

    def test_web_search_needs_its_server(self):
        self.assertNotIn("web-search", skills.for_role(self.r.inst, "researcher"))
        r = FakeInstance({"mcp": {"researcher": ["@mcp-web-search"]}})
        try:
            self.assertIn("web-search", skills.for_role(r.inst, "researcher"))
            self.assertNotIn("web-search", skills.for_role(r.inst, "explorer"))
        finally:
            r.cleanup()

    def test_check_names_an_unknown_skill(self):
        d = Path(tempfile.mkdtemp(prefix="ek-skill-check-"))
        try:
            (d / "instance.json").write_text(json.dumps(core.merge(CONFIG, {"skills": {"developer": ["nope"]},
                                                                            "skills_off": ["gone"]})))
            errors = install.check_config(d)
            self.assertIn("skills.developer: no skill named nope in the kit or in overlay/skills", errors)
            self.assertIn("skills_off: no skill named gone", errors)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_installer_loads_its_own_workspace_copies(self):
        cfg = gen.installer_config()
        uris = [r for r in cfg["resources"] if r.startswith("skill://")]
        self.assertEqual(uris, [f"skill://{core.KIT}/.kiro/skills/{n}/SKILL.md" for n in ("grill-me", "grilling", "lavish")])


class WorkspaceCopies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = RealInstance({"mcp": {"researcher": ["@mcp-web-search"]}})
        cls.root = cls.r.root

    @classmethod
    def tearDownClass(cls):
        cls.r.cleanup()

    def agents(self):
        return {p.stem: json.loads(p.read_text()) for p in (self.root / ".kiro/agents").glob("*.json")}

    def skill_names(self, role):
        prefix = f"skill://{self.root}/.kiro/skills/"
        return [u[len(prefix):-len("/SKILL.md")] for u in self.agents()[role]["resources"] if u.startswith(prefix)]

    def gen(self):
        p = self.r.effort("gen")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_each_agent_loads_only_workspace_copies(self):
        for role, cfg in self.agents().items():
            for uri in cfg["resources"]:
                path = uri.split("://", 1)[1].split("*")[0]
                self.assertTrue(path.startswith(str(self.root)), f"{role} loads {uri}, outside the instance")
                if uri.startswith("skill://"):
                    self.assertTrue(uri.startswith(f"skill://{self.root}/.kiro/skills/"), uri)
        for name, src in skills.kit_skills().items():
            copy = self.root / ".kiro/skills" / name
            if not copy.exists():
                continue
            for f in (p for p in src.rglob("*") if p.is_file()):
                c = copy / f.relative_to(src)
                self.assertFalse(c.is_symlink(), c)
                self.assertEqual(c.read_bytes(), f.read_bytes(), c)

    def test_every_skill_of_every_role_is_installed(self):
        for role in self.agents():
            for name in self.skill_names(role):
                self.assertTrue((self.root / ".kiro/skills" / name / "SKILL.md").is_file(), f"{role}: {name}")
        self.assertIn("web-search", self.skill_names("researcher"))
        self.assertTrue((self.root / ".kiro/skills/asd-ste100/references/writing-rules.md").is_file())

    def test_an_overlay_skill_replaces_extends_and_narrows(self):
        cfg_path = self.root / "instance.json"
        before = cfg_path.read_text()
        own = self.root / "overlay/skills/lavish"
        extra = self.root / "overlay/skills/scaffold"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("---\nname: lavish\ndescription: the project's own page rules\n---\n")
        extra.mkdir(parents=True)
        (extra / "SKILL.md").write_text("---\nname: scaffold\ndescription: scaffold a module\n---\n")
        try:
            self.gen()
            self.assertIn("the project's own page rules", (self.root / ".kiro/skills/lavish/SKILL.md").read_text())
            for role in ("supervisor", "developer", "explorer"):
                self.assertIn("scaffold", self.skill_names(role))
            cfg = json.loads(before)
            cfg["skills"] = {"developer": ["scaffold"]}
            cfg_path.write_text(json.dumps(cfg))
            self.gen()
            self.assertIn("scaffold", self.skill_names("developer"))
            self.assertNotIn("scaffold", self.skill_names("explorer"))
        finally:
            cfg_path.write_text(before)
            shutil.rmtree(own)
            shutil.rmtree(extra)
            self.gen()
        self.assertFalse((self.root / ".kiro/skills/scaffold").exists())
        self.assertEqual((self.root / ".kiro/skills/lavish/SKILL.md").read_bytes(),
                         (core.KIT / "skills/lavish/SKILL.md").read_bytes())

    def test_skills_off_removes_the_copy(self):
        cfg_path = self.root / "instance.json"
        before = cfg_path.read_text()
        cfg = json.loads(before)
        cfg["skills_off"] = ["lavish"]
        cfg_path.write_text(json.dumps(cfg))
        try:
            self.gen()
            self.assertFalse((self.root / ".kiro/skills/lavish").exists())
            self.assertNotIn("lavish", self.skill_names("supervisor"))
        finally:
            cfg_path.write_text(before)
            self.gen()
        self.assertTrue((self.root / ".kiro/skills/lavish/SKILL.md").is_file())

    def test_the_kit_command_is_on_the_session_path(self):
        wrapper = self.root / "bin/effortkit"
        self.assertTrue(os.access(wrapper, os.X_OK))
        env = {**self.r.env, "PATH": f"{self.root / 'bin'}{os.pathsep}{self.r.env['PATH']}"}
        p = sh("effortkit", "skills", env=env, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertRegex(p.stdout, r"lavish\s+MIT")


class KiroHome(unittest.TestCase):
    """kiro-cli adds the skills and the steering of its home to every agent, so sessions get a home of the instance."""

    def setUp(self):
        self.machine = Path(tempfile.mkdtemp(prefix="ek-machine-"))
        (self.machine / "settings").mkdir()
        (self.machine / "settings/mcp.json").write_text('{"mcpServers": {}}')
        (self.machine / "skills/private").mkdir(parents=True)
        (self.machine / "skills/private/SKILL.md").write_text("---\nname: private\ndescription: x\n---\n")
        (self.machine / "steering").mkdir()
        (self.machine / "steering/personal.md").write_text("A personal rule.\n")
        self.r = RealInstance()
        self.r.env["KIRO_HOME"] = str(self.machine)

    def tearDown(self):
        self.r.cleanup()
        shutil.rmtree(self.machine, ignore_errors=True)

    def test_sessions_get_a_home_with_the_machine_settings_only(self):
        fake = self.r.dir / "bin/kiro-cli"
        fake.write_text('#!/bin/sh\necho "KIRO_HOME=$KIRO_HOME"\nexit 0\n')
        p = self.r.effort("home")
        self.assertEqual(p.returncode, 0, p.stderr)
        home = self.r.root / ".kiro-home"
        self.assertIn(f"KIRO_HOME={home}", p.stdout)
        self.assertEqual(sorted(x.name for x in home.iterdir()), ["settings"])
        self.assertEqual(sorted(x.name for x in (home / "settings").iterdir()), ["mcp.json"])
        self.assertEqual(os.readlink(home / "settings/mcp.json"), str(self.machine / "settings/mcp.json"))
        self.assertIn("/.kiro-home/", (self.r.root / ".gitignore").read_text())

    def test_a_nested_effort_command_keeps_the_machine_settings(self):
        env = {**self.r.env, "KIRO_HOME": str(self.r.root / ".kiro-home"), "EFFORTKIT_MACHINE_KIRO_HOME": str(self.machine)}
        p = sh(sys.executable, core.KIT / "bin/effort", "gen", env=env, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(os.readlink(self.r.root / ".kiro-home/settings/mcp.json"), str(self.machine / "settings/mcp.json"))


class ProcessCheck(unittest.TestCase):
    def test_proc_and_ps_agree(self):
        for proc in (True, False):
            self.assertIn("python", core.process_cmdline(os.getpid(), proc=proc) or "", proc)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        for proc in (True, False):
            self.assertIsNone(core.process_cmdline(dead.pid, proc=proc), proc)


if __name__ == "__main__":
    unittest.main()
