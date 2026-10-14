"""The installer: the layout it creates, the config checks, the repair, and an existing clone as the project."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.sandbox import CONFIG, EFFORT, EFFORTKIT, FakeInstance, RealInstance, git_env, sh
from effortkit import core, install


class Install(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = RealInstance()

    @classmethod
    def tearDownClass(cls):
        cls.r.cleanup()

    def test_layout(self):
        root, env = self.r.root, self.r.env
        cfg = json.loads((root / "instance.json").read_text())
        self.assertEqual((cfg["name"], cfg["repo"]["default_base"]), ("toy", "origin/main"))
        for d in ("worklog/plan", "worklog/knowledge/inbox", "worklog/improvements/inbox", "trees", "locks",
                  "overlay/steering", "overlay/agents", "overlay/skills"):
            self.assertTrue((root / d).is_dir(), d)
        tracked = sh("git", "ls-files", cwd=root, env=env).stdout.split()
        self.assertEqual(sorted(tracked), [".gitignore", "instance.json", "overlay/agents/.gitkeep",
                                           "overlay/skills/.gitkeep", "overlay/steering/project.md"])
        self.assertEqual(sh("git", "status", "--porcelain", cwd=root, env=env).stdout, "")
        self.assertIn("effort: new worklog", sh("git", "log", "--format=%s", cwd=root / "worklog", env=env).stdout)
        self.assertIn("origin/main", sh("git", "branch", "-r", cwd=root / "product.git", env=env).stdout)
        for repo in (root / "product.git/hooks", root / ".git/hooks"):
            self.assertTrue(os.access(repo / "commit-msg", os.X_OK))
            self.assertTrue(os.access(repo / "pre-push", os.X_OK))
        agents = sorted(p.stem for p in (root / ".kiro/agents").glob("*.json"))
        self.assertEqual(agents, sorted(["supervisor", *core.BUILTIN_ROLES]))
        self.assertTrue(os.access(root / "bin/effort", os.X_OK))
        registry = json.loads((self.r.dir / "xdg/effortkit/instances.json").read_text())
        self.assertIn(str(root), registry["instances"])

    def test_a_second_install_into_the_same_folder_is_refused(self):
        p = self.r.kit("install", "--dir", self.r.root, "--config", self.r.answers)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("holds an instance already", p.stderr)

    def test_repair_restores_the_generated_files(self):
        (self.r.root / "bin/effort").unlink()
        (self.r.root / ".kiro/agents/tester.json").unlink()
        p = self.r.kit("install", "--dir", self.r.root, "--repair")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.r.root / "bin/effort").is_file())
        self.assertTrue((self.r.root / ".kiro/agents/tester.json").is_file())

    def test_check_validates_with_kiro_cli(self):
        if not shutil.which("kiro-cli", path=os.environ["PATH"]):
            self.skipTest("kiro-cli is not installed")
        env = dict(self.r.env)
        env["PATH"] = os.environ["PATH"]  # The real kiro-cli, not the fake one.
        p = sh(sys.executable, EFFORTKIT, "check", self.r.root, "--validate", env=env, check=False)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ok", p.stdout)

    def test_an_existing_clone_as_the_project(self):
        target = self.r.dir / "inst-local"
        clone = self.r.dir / "work"
        sh("git", "clone", "-q", self.r.remote, clone, env=self.r.env)
        answers = {k: v for k, v in CONFIG.items() if k != "effortkit"}
        answers["name"] = "toy-local"
        answers["repo"] = {"path": str(clone)}
        a = self.r.dir / "answers-local.json"
        a.write_text(json.dumps(answers))
        p = self.r.kit("install", "--dir", target, "--config", a)
        self.assertEqual(p.returncode, 0, p.stderr)
        inst = core.Instance(target)
        self.assertEqual((inst.product, inst.config["repo"]["default_base"]), (clone, "origin/main"))
        self.assertFalse((target / "product.git").exists())
        env = {**self.r.env, "EFFORTKIT_INSTANCE": str(target)}
        p = sh(sys.executable, EFFORT, "new", "loc-a", "--kind", "code", env=env, check=False)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn(str(target / "trees/loc-a"), sh("git", "worktree", "list", cwd=clone, env=self.r.env).stdout)


class CheckConfig(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ek-check-"))
        (self.dir / "overlay/agents").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def check(self, **changes):
        cfg = core.merge(CONFIG, changes)
        (self.dir / "instance.json").write_text(json.dumps(cfg))
        return install.check_config(self.dir)

    def test_a_good_config_has_no_errors(self):
        self.assertEqual(self.check(), [])

    def test_each_problem_is_named(self):
        cases = [
            ({"commit": {"subject_regex": "(unclosed"}}, "commit.subject_regex is not a valid regex"),
            ({"tests": {"commands": ["npm test"], "patterns": ["make test"]}}, "no tests.patterns entry matches 'npm test'"),
            ({"roles": {"auditor": {"profile": "reader"}}}, "needs its prompt in overlay/agents/auditor.md"),
            ({"roles": {"explorer": {"profile": "root"}}}, "profile 'root' must be one of"),
            ({"kinds": {"docs": {"repo": "product", "lane": "lane-docs"}}}, "lane skill lane-docs is in neither"),
            ({"kinds": {"odd": {"repo": "elsewhere"}}}, "repo must be product, kit, instance or null"),
            ({"improve": {"trigger": "hourly"}}, "improve.trigger must be on-close or manual"),
            ({"forbidden_commands": [{"pattern": "^x"}]}, "needs a reason"),
            ({"push": {"protected_branches": ["main; rm -rf /"]}}, "not a plain branch name"),
            ({"name": "Bad Name"}, "must be 3 to 50 lowercase"),
        ]
        for change, needle in cases:
            errors = self.check(**change)
            self.assertTrue(any(needle in e for e in errors), f"{change}: {errors}")

    def test_an_unknown_placeholder_in_the_overlay_is_named(self):
        (self.dir / "overlay/agents/developer.md").write_text("Use {{no_such_thing}}.\n")
        errors = self.check()
        self.assertTrue(any("unknown placeholder {{no_such_thing}}" in e for e in errors), errors)

    def test_a_documented_test_command_with_a_placeholder_matches_its_pattern(self):
        self.assertEqual(self.check(tests={"commands": ["mvn -pl <module> -am test"],
                                           "patterns": [r"mvn(?: -pl \S+| -am| -q)* test(?: -D\S+)*"]}), [])


class McpServers(unittest.TestCase):
    def test_names_only_and_the_settings_stay_secret(self):
        home = Path(tempfile.mkdtemp(prefix="ek-home-"))
        try:
            (home / ".kiro/settings").mkdir(parents=True)
            (home / ".kiro/settings/mcp.json").write_text(json.dumps({"mcpServers": {
                "mcp-web-search": {"command": "x"}, "mcp-tickets": {"command": "y", "env": {"TOKEN": "s3cret"}}}}))
            env = {**git_env(home), "HOME": str(home)}
            p = sh(sys.executable, EFFORTKIT, "mcp-servers", env=env, cwd=home, check=False)
            self.assertEqual((p.returncode, p.stdout), (0, "@mcp-web-search\n@mcp-tickets\n"))
            r = FakeInstance()
            try:
                r.env["HOME"] = str(home)
                code, err = r.gate("explorer", "read", {"operations": [{"mode": "Line", "path": str(home / ".kiro/settings/mcp.json")}]},
                                   cwd=r.tree("e1"))
                self.assertEqual(code, 2, err)
                self.assertIn("holds credentials", err)
            finally:
                r.cleanup()
        finally:
            shutil.rmtree(home, ignore_errors=True)


class InstallRefusals(unittest.TestCase):
    def test_a_folder_that_is_not_empty_is_refused(self):
        d = Path(tempfile.mkdtemp(prefix="ek-busy-"))
        try:
            (d / "something.txt").write_text("x")
            with self.assertRaises(install.InstallError) as ctx:
                install.install(d, {"repo": {"url": "/nonexistent"}}, clone=False, log=lambda *_: None)
            self.assertIn("is not empty", str(ctx.exception))
            with self.assertRaises(install.InstallError) as ctx:
                install.install(d / "new", {"name": "x y", "repo": {"url": "/nonexistent"}}, clone=False, log=lambda *_: None)
            self.assertIn("lowercase", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
