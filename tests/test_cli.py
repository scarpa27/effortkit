"""The effort command against a toy project. A fake kiro-cli prints its arguments and exits 0, so no model runs."""
import json
import re
import subprocess
import time
import unittest
from pathlib import Path

from tests.sandbox import RealInstance, sh
from effortkit import improve


class EffortCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = RealInstance()

    @classmethod
    def tearDownClass(cls):
        cls.r.cleanup()

    def ok(self, *args):
        p = self.r.effort(*args)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        return p.stdout

    def commit_in(self, tree, name, text="x\n"):
        (tree / name).write_text(text)
        sh("git", "add", name, cwd=tree, env=self.r.env)
        sh("git", "commit", "-qm", f"TOY-1: add {name}", cwd=tree, env=self.r.env)

    def test_new_and_preflight(self):
        out = self.ok("new", "feat-a", "--kind", "code", "--ticket", "TOY-7")
        self.assertIn("ok   commit-msg hook", out)
        e = self.r.inst.load_effort("feat-a")
        self.assertEqual((e.kind, e.data["branch"], e.data["base_ref"]), ("code", "TOY-7/feat-a", "origin/main"))
        self.assertTrue((e.tree / ".kiro").is_symlink())
        self.assertEqual(e.stage(), "EXPLORING")
        self.assertEqual(sh("git", "status", "--porcelain", cwd=e.tree, env=self.r.env).stdout, "")
        self.assertEqual(self.r.effort("preflight", "feat-a").returncode, 0)
        bad = self.r.effort("new", "feat-bad", "--kind", "code", "--ticket", "BAD-1")
        self.assertIn("--ticket must match", bad.stderr)
        self.assertIn("unknown kind", self.r.effort("new", "feat-bad", "--kind", "nope").stderr)

    def test_a_commit_with_a_wrong_subject_fails_in_the_hook(self):
        self.ok("new", "feat-hook", "--kind", "code")
        tree = self.r.inst.load_effort("feat-hook").tree
        (tree / "x.txt").write_text("x")
        sh("git", "add", "x.txt", cwd=tree, env=self.r.env)
        p = sh("git", "commit", "-qm", "no key", cwd=tree, env=self.r.env, check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("commit-msg REFUSED", p.stderr)
        sh("git", "commit", "-qm", "TOY-2: with a key", cwd=tree, env=self.r.env)

    def test_new_continues_an_existing_branch(self):
        self.ok("new", "cont-one", "--kind", "code", "--ticket", "TOY-3")
        first = self.r.inst.load_effort("cont-one")
        self.commit_in(first.tree, "a.txt")
        tip = sh("git", "rev-parse", "HEAD", cwd=first.tree, env=self.r.env).stdout.strip()
        self.assertIn("on no remote branch", self.r.effort("close", "cont-one").stderr)
        self.ok("close", "cont-one", "--force")
        self.ok("new", "cont-two", "--kind", "code", "--branch", "TOY-3/cont-one")
        second = self.r.inst.load_effort("cont-two")
        self.assertEqual((second.data["base_sha"], second.data["branch"]), (tip, "TOY-3/cont-one"))

    def test_sessions_get_the_identity_and_the_instance_command(self):
        self.ok("new", "sess-a", "--kind", "code")
        out = self.ok("start", "sess-a")
        tree = self.r.inst.load_effort("sess-a").tree
        self.assertIn("FAKE kiro args: chat --agent supervisor", out)
        self.assertIn(f"EFFORTKIT_EFFORT=sess-a PWD={tree}", out)
        self.assertIn(f"PATH0={self.r.root}/bin", out)
        home = self.ok("home")
        self.assertIn(f"EFFORTKIT_EFFORT= PWD={self.r.root}", home)

    def test_approve_needs_a_terminal(self):
        self.ok("new", "appr-a", "--kind", "triage")
        (self.r.plan("appr-a") / "task.md").write_text("# Task\n")
        p = self.r.effort("approve", "appr-a")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("needs a terminal", p.stderr)
        self.assertFalse((self.r.plan("appr-a") / "approval.json").exists())

    def test_runs_in_the_foreground_and_detached(self):
        self.ok("new", "run-a", "--kind", "code")
        brief = self.r.plan("run-a") / "briefs/b.md"
        brief.write_text("Explore the app.\n")
        out = self.ok("run", "run-a", "--role", "explorer", "--brief", str(brief))
        self.assertIn("FAKE kiro args: chat --agent explorer --no-interactive Explore the app.", out)
        self.assertIn("EFFORTKIT_EFFORT=run-a", out)
        self.assertIn("no role named", self.r.effort("run", "run-a", "--role", "nobody", "--brief", str(brief)).stderr)
        out = self.ok("run", "run-a", "--role", "reviewer", "--brief", str(brief), "--detach")
        run_id = re.search(r"run (\S+) started", out).group(1)
        waited = self.r.effort("wait", run_id, "--timeout", "60")
        self.assertEqual(waited.returncode, 0, waited.stdout + waited.stderr)
        self.assertIn("FAKE kiro args: chat --agent reviewer", waited.stdout)
        self.assertIn("done, exit 0", waited.stdout)

    def test_status_collisions_and_close(self):
        for name in ("col-a", "col-b"):
            self.ok("new", name, "--kind", "code")
            (self.r.inst.load_effort(name).tree / "app.py").write_text(f"print('{name}')\n")
        out = self.ok("status", "--collisions")
        self.assertRegex(out, r"collision col-a <-> col-b: app.py")
        self.assertIn("uncommitted changes", self.r.effort("close", "col-a").stderr)
        self.ok("close", "col-a", "--force")
        e = self.r.inst.load_effort("col-a")
        self.assertTrue(e.closed)
        self.assertFalse(e.tree.exists())
        self.assertIn("col-a", sh("git", "branch", "--list", "effort/col-a", cwd=self.r.inst.product, env=self.r.env).stdout)

    def test_kb_and_report(self):
        path = self.ok("kb", "add", "project", "The", "build", "needs", "a", "cache.").strip()
        self.assertTrue(path.endswith("-home-owner.md"))
        self.assertEqual(Path(path).read_text(), "target: project.md\n\nThe build needs a cache.\n")
        self.assertIn("no knowledge topic", self.r.effort("kb", "add", "nope", "x").stderr)
        path = self.ok("report", "The tester prompt names no test folder.", "--scope", "overlay",
                       "--area", "prompt:tester", "--severity", "blocker").strip()
        rep = improve.parse_report(self.r.inst, Path(path))
        self.assertEqual((rep.scope, rep.area, rep.severity, rep.effort, rep.role),
                         ("overlay", "prompt:tester", "blocker", "home", "owner"))
        rep.path.unlink()

    def test_gen_check_and_overlay_prompts(self):
        self.assertEqual(self.ok("gen", "--check").strip(), "current")
        extra = self.r.root / "overlay/agents/tester.md"
        extra.write_text("- Put the fixtures in `tests/fixtures/`.\n")
        try:
            self.assertEqual(self.r.effort("gen", "--check").returncode, 1)
            self.ok("gen")
            text = (self.r.root / ".kiro/agents/tester.md").read_text()
            self.assertIn("<Project rules for this role>\n- Put the fixtures in `tests/fixtures/`.", text)
            self.assertEqual(self.ok("gen", "--check").strip(), "current")
        finally:
            extra.unlink()
            self.ok("gen")

    def test_a_custom_role_appears_and_disappears(self):
        cfg_path = self.r.root / "instance.json"
        before = cfg_path.read_text()
        cfg = json.loads(before)
        cfg["roles"] = {"log-reader": {"profile": "reader", "description": "Reads the logs", "artifact": "log-analysis.md"}}
        (self.r.root / "overlay/agents/log-reader.md").write_text("# log-reader\nYou read logs in {{reference}}.\n")
        cfg_path.write_text(json.dumps(cfg))
        try:
            self.ok("gen")
            agent = json.loads((self.r.root / ".kiro/agents/log-reader.json").read_text())
            self.assertTrue(agent["toolsSettings"]["shell"]["denyByDefault"])
            self.assertIn(str(self.r.root / "worklog/reference"), (self.r.root / ".kiro/agents/log-reader.md").read_text())
            sup = json.loads((self.r.root / ".kiro/agents/supervisor.json").read_text())
            self.assertIn("log-reader", sup["toolsSettings"]["subagent"]["availableAgents"])
        finally:
            cfg_path.write_text(before)
            (self.r.root / "overlay/agents/log-reader.md").unlink()
            self.ok("gen")
        self.assertFalse((self.r.root / ".kiro/agents/log-reader.json").exists())

    def test_plan_review_pages(self):
        self.ok("new", "page-a", "--kind", "triage")
        plan = self.r.plan("page-a")
        (plan / "task.md").write_text("# Task: a page\n## Request\nShow it.\n## Waves\n### Wave 1: x\n")
        (plan / "questions.md").write_text("## Q1: Which folder?\nRecommended: tests/\nDepends on: the layout\n")
        (plan / "decision.md").write_text("# Decisions\n## D1: The retention\n- (a) 24 h\n- (b) 7 days\n- Recommendation: (b)\n")
        page = self.ok("plan-review", "page-a").splitlines()[0]
        html = Path(page).read_text()
        self.assertIn('data-lavish-question="Q1"', html)
        page = self.ok("plan-review", "page-a", "decision.md").splitlines()[0]
        html = Path(page).read_text()
        self.assertIn('value="B" data-label="7 days" checked', html)


class ImprovementLoop(unittest.TestCase):
    """Reports and gate signals become an improvement round, and close files each decided report into the ledger."""

    def setUp(self):
        self.r = RealInstance({"improve": {"trigger": "on-close", "threshold": 2}})
        self.inst = self.r.inst

    def tearDown(self):
        self.r.cleanup()

    def report(self, name, scope, severity="friction"):
        self.inst.reports.mkdir(parents=True, exist_ok=True)
        p = self.inst.reports / name
        p.write_text(f"scope: {scope}\narea: gate\nseverity: {severity}\n\n## What happened\nx\n")
        return p

    def test_a_round_per_layer_then_settlement_and_stats(self):
        self.report("20261023T100000Z-feat-x-explorer.md", "kit")
        self.report("20261023T100001Z-feat-x-reviewer.md", "unsure", "blocker")
        self.report("20261023T100002Z-feat-x-tester.md", "overlay")
        log = self.inst.locks / "gate-home.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({"time": "2026-10-23T10:00:00Z", "decision": "refuse", "gate": "commands",
                                   "role": "reviewer", "reason": "role reviewer does not run the tests.", "call": "make test"}) + "\n")
        p = self.r.effort("improve", "--no-run")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        rounds = {e.kind: e for e in self.inst.efforts() if e.name.startswith("improve-")}
        self.assertEqual(sorted(rounds), ["kit", "overlay"])
        kit, overlay = rounds["kit"], rounds["overlay"]
        self.assertEqual(sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=kit.tree, env=self.r.env).stdout.strip(),
                         f"workflow/{kit.name}")
        self.assertTrue((kit.tree / "lib/effortkit/gate.py").is_file())
        self.assertTrue((overlay.tree / "instance.json").is_file())
        self.assertIn("1x gate commands, role reviewer: role reviewer does not run the tests.",
                      (kit.plan / "signals.md").read_text())
        brief = next((kit.plan / "briefs").glob("*-improver.md")).read_text()
        self.assertIn("100000Z-feat-x-explorer.md", brief)
        self.assertIn("100001Z-feat-x-reviewer.md", brief)
        self.assertNotIn("tester.md", brief)
        self.assertIn("feat-x-tester.md", next((overlay.plan / "briefs").glob("*-improver.md")).read_text())
        self.assertTrue(improve.state(self.inst)["signals_until"])
        (kit.plan / "triage.md").write_text(
            "# Triage\n## Decisions\n"
            "- 20261023T100000Z-feat-x-explorer.md: accepted - T1\n"
            "- `20261023T100001Z-feat-x-reviewer.md`: rejected - the rule protects the lab\n")
        p = self.r.effort("close", kit.name)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn("report 20261023T100000Z-feat-x-explorer.md: accepted", p.stdout)
        done = sorted(x.name for x in (self.inst.reports_done / kit.name).iterdir())
        self.assertEqual(done, ["20261023T100000Z-feat-x-explorer.md", "20261023T100001Z-feat-x-reviewer.md"])
        self.assertEqual([r.name for r in improve.pending_reports(self.inst)], ["20261023T100002Z-feat-x-tester.md"])
        ledger = improve.ledger(self.inst)
        self.assertEqual([(x["decision"], x["from_effort"], x["from_role"], x["severity"]) for x in ledger],
                         [("accepted", "feat-x", "explorer", "friction"), ("rejected", "feat-x", "reviewer", "blocker")])
        stats = self.r.effort("improve", "stats").stdout
        self.assertRegex(stats, r"feat-x\s+-\s+1\s+2\s+0")
        self.assertIn("open: 1; settled: accepted 1, rejected 1", stats)

    def test_the_improver_runs_in_the_round(self):
        self.report("20261023T100000Z-feat-y-explorer.md", "kit")
        p = self.r.effort("improve", "--scope", "kit")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn("FAKE kiro args: chat --agent improver --no-interactive # Improvement round improve-kit-", p.stdout)

    def test_close_starts_a_round_at_the_threshold(self):
        p = self.r.effort("new", "plain-a", "--kind", "triage")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.report("20261023T100000Z-plain-a-explorer.md", "kit")
        self.report("20261023T100001Z-plain-a-debugger.md", "overlay")
        p = self.r.effort("close", "plain-a")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn("Starting an improvement round in the background", p.stdout)
        runs = re.findall(r"improver run (\S+):", p.stdout)
        self.assertEqual(len(runs), 2, p.stdout)
        for run_id in runs:
            w = self.r.effort("wait", run_id, "--timeout", "60")
            self.assertIn("FAKE kiro args: chat --agent improver", w.stdout)
        p = self.r.effort("new", "plain-b", "--kind", "triage")
        p = self.r.effort("close", "plain-b")
        self.assertIn("is still open, so no new round starts", p.stdout)

    def test_nothing_to_improve(self):
        p = self.r.effort("improve")
        self.assertIn("nothing to improve", p.stdout)


if __name__ == "__main__":
    unittest.main()
