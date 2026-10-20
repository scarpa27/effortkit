"""effortkit init: the answers that the detector proposes for a repository, and their path into an instance."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.sandbox import EFFORTKIT, git_env, sh
from effortkit import core, detect, install

POM = "<project><modules><module>core</module><module>app</module></modules></project>\n"


class Repos:
    """Fixture repositories in a temporary folder, with a private git config."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ek-init-test-"))
        self.env = git_env(self.dir)

    def make(self, name: str, files: dict[str, str], commits: list[tuple[str, str]], branches=(), bare=True) -> Path:
        work = self.dir / f"{name}-work"
        work.mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=work, env=self.env)
        for rel, text in files.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text)
        sh("git", "add", "-A", cwd=work, env=self.env)
        for author, subject in commits:
            sh("git", "-c", f"user.name={author}", "commit", "-q", "--allow-empty", "-m", subject, cwd=work, env=self.env)
        for b in branches:
            sh("git", "branch", b, cwd=work, env=self.env)
        if not bare:
            return work
        sh("git", "clone", "-q", "--bare", work, self.dir / f"{name}.git", env=self.env)
        return self.dir / f"{name}.git"

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class Detect(unittest.TestCase):
    def setUp(self):
        self.repos = Repos()

    def tearDown(self):
        self.repos.cleanup()

    def test_maven_with_tickets_a_people_tag_and_a_bot_tag(self):
        commits = [("Alice", "PROJ-12: Add the parser"), ("release-bot", "[maven-release-plugin] prepare release v1"),
                   ("Alice", "[nojira] Tidy the imports"), ("Bob", "PROJ-13: Fix the reader"),
                   ("release-bot", "[maven-release-plugin] prepare for next development iteration"),
                   ("Bob", "[nojira] Update the docs"), ("Alice", "PROJ-14: Add the writer")]
        src = self.repos.make("shop", {"pom.xml": POM, "core/pom.xml": "<project/>\n"}, commits,
                              branches=("PROJ-12/parser", "PROJ-13/reader"))
        a = detect.detect(str(src))
        self.assertEqual(a["repo"], {"url": str(src), "default_base": "origin/main"})
        self.assertEqual(a["ticket"], {"regex": r"^PROJ-\d+$", "example": "PROJ-14"})
        self.assertEqual(a["commit"], {"subject_regex": r"^(?:PROJ-\d+: |\[nojira\] )\S",
                                       "subject_help": "PROJ-NNNN: <subject> or [nojira] <subject>"})
        rule = a["commit"]["subject_regex"]
        for _, s in commits:
            self.assertEqual(bool(re.match(rule, s)), not s.startswith("[maven"), s)
        self.assertEqual(a["branch"], {"template": "{ticket}/{name}"})
        self.assertEqual(a["tests"], {"commands": ["mvn -pl <module> -am test"]})
        self.assertEqual([f["pattern"] for f in a["forbidden_commands"]], [detect.PUBLISH["maven"]["pattern"]])
        self.assertIn("maven-release-plugin come only from authors with no ticket commit", a["_evidence"]["commit"])

    def test_node_with_conventional_commits_from_a_working_clone(self):
        files = {"package.json": json.dumps({"scripts": {"test": "jest"}}), "package-lock.json": "{}\n"}
        bare = self.repos.make("web", files, [("Ann", "feat: Add the cart"), ("Ann", "fix(api): Retry the call"),
                                              ("Ann", "chore: Bump jest")])
        work = self.repos.dir / "web-clone"
        sh("git", "clone", "-q", bare, work, env=self.repos.env)
        a = detect.detect(str(work))
        self.assertEqual(a["repo"], {"url": str(bare), "default_base": "origin/main"})
        self.assertEqual(a["commit"]["subject_regex"], detect.CONVENTIONAL.pattern)
        self.assertNotIn("ticket", a)
        self.assertEqual((a["tests"], a["tree_setup"]), ({"commands": ["npm test"]}, ["npm ci"]))
        self.assertEqual([f["pattern"] for f in a["forbidden_commands"]], [detect.PUBLISH["node"]["pattern"]])

    def test_python_and_make_without_a_convention(self):
        files = {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
                 "Makefile": "test:\n\tpytest\ndeploy:\n\t./ship\n", "tests/test_a.py": "def test_a(): pass\n"}
        src = self.repos.make("lib", files, [("Cy", "Fix the bug"), ("Cy", "Add a feature"), ("Cy", "Refactor")])
        a = detect.detect(str(src))
        self.assertNotIn("commit", a)
        self.assertNotIn("ticket", a)
        self.assertEqual(a["tests"], {"commands": ["python3 -m pytest <path>", "make test"]})
        self.assertEqual([f["pattern"] for f in a["forbidden_commands"]],
                         [detect.PUBLISH["python"]["pattern"], r"^make\b.*\b(deploy)\b"])
        self.assertIn("any subject passes", a["_evidence"]["commit"])

    def test_go_and_rust_in_a_clone_without_a_remote(self):
        src = self.repos.make("tool", {"go.mod": "module x\n", "Cargo.toml": "[package]\nname = 'x'\n"},
                              [("Dee", "Start")], bare=False)
        a = detect.detect(str(src))
        self.assertEqual(a["repo"], {"path": str(core.real(src)), "default_base": "main"})
        self.assertEqual(a["tests"], {"commands": ["go test <packages>", "cargo test"]})
        self.assertNotIn("forge", a)

    def test_the_name_the_description_and_the_forge(self):
        self.assertEqual(detect.instance_name("git@gitlab.example.com:Group/My_Project.git"), "my-project")
        self.assertEqual(detect.instance_name("https://example.com/a/x"), "x-project")
        self.assertEqual(detect.forge_host("git@gitlab.example.com:group/shop.git"), "gitlab.example.com")
        self.assertEqual(detect.forge_host("https://github.com/org/shop.git"), "github.com")
        self.assertIsNone(detect.forge_host("/srv/git/shop.git"))
        readme = "# Shop\n\n[![build](https://x/b.svg)](https://x)\n\nShop is a **web shop** for [books](https://b). It sells.\n"
        src = self.repos.make("shop", {"README.md": readme}, [("Eve", "Start")])
        a = detect.detect(str(src))
        self.assertEqual(a["description"], "Shop is a web shop for books.")
        self.assertIn("a guess", a["_evidence"]["description"])

    def test_the_temporary_clone_is_removed(self):
        src = self.repos.make("tmp", {"go.mod": "module x\n"}, [("Fay", "Start")])
        before = set(Path(tempfile.gettempdir()).glob("effortkit-init-*"))
        detect.detect(str(src))
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("effortkit-init-*")), before)
        with self.assertRaises(RuntimeError):
            detect.detect(str(self.repos.dir / "missing.git"))
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("effortkit-init-*")), before)


class InitToInstall(unittest.TestCase):
    def test_the_answers_install_and_the_evidence_stays_on_record(self):
        repos = Repos()
        try:
            src = repos.make("shop", {"pom.xml": POM}, [("Al", "PROJ-1: Start"), ("Al", "PROJ-2: More")])
            answers = repos.dir / "answers.json"
            p = sh(sys.executable, EFFORTKIT, "init", src, "--out", answers, env=repos.env, check=False)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("commit: 2 of 2 subjects start with PROJ-<number>", p.stderr)
            target = repos.dir / "inst"
            p = sh(sys.executable, EFFORTKIT, "install", "--dir", target, "--config", answers, env=repos.env, check=False)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            self.assertEqual(install.check_config(target), [])
            cfg = json.loads((target / "instance.json").read_text())
            self.assertNotIn("_evidence", cfg)
            self.assertEqual(cfg["commit"]["subject_help"], "PROJ-NNNN: <subject>")
            record = json.loads((target / "worklog/reference/install-answers.json").read_text())
            self.assertIn("_evidence", record)
        finally:
            repos.cleanup()


if __name__ == "__main__":
    unittest.main()
