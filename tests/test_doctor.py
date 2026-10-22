"""effortkit doctor and effortkit setup, on a PATH that the test controls, with a fake kiro-cli."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.sandbox import EFFORTKIT, RealInstance, git_env, sh
from effortkit import core


class Machine:
    """A bin folder with python3, git and a fake kiro-cli, and nothing else."""

    def __init__(self, kiro_version="2.33.1", logged_in=True):
        self.dir = Path(tempfile.mkdtemp(prefix="ek-doctor-"))
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for tool in ("git",):
            (self.bin / tool).symlink_to(shutil.which(tool))
        (self.bin / "python3").symlink_to(sys.executable)
        who = 'echo "Logged in with Builder ID"; exit 0' if logged_in else 'echo "Not logged in"; exit 1'
        (self.bin / "kiro-cli").write_text(f'#!/bin/sh\ncase "$1" in\n  --version) echo "kiro-cli {kiro_version}" ;;\n'
                                           f'  whoami) {who} ;;\nesac\n')
        (self.bin / "kiro-cli").chmod(0o755)
        self.env = {**git_env(self.dir), "PATH": str(self.bin)}

    def kit(self, *args):
        return sh(sys.executable, EFFORTKIT, *args, env=self.env, check=False, cwd=self.dir)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class Doctor(unittest.TestCase):
    def test_a_bare_machine_warns_about_the_missing_tools(self):
        m = Machine()
        try:
            p = m.kit("doctor")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            for line in ("ok   kiro-cli: 2.33.1", "ok   kiro-cli login: logged in", "WARN tmux: missing",
                         "WARN rg: missing", "WARN npx: missing", "ok   commit signing: not configured",
                         "WARN effortkit on PATH: missing", "ok   kit skills: every skill matches its lock entry",
                         "ok   instances: none registered yet"):
                self.assertIn(line, p.stdout)
        finally:
            m.cleanup()

    def test_a_logged_out_kiro_fails_and_another_version_warns(self):
        m = Machine(kiro_version="2.40.0", logged_in=False)
        try:
            p = m.kit("doctor")
            self.assertEqual(p.returncode, 1)
            self.assertIn("FAIL kiro-cli login: not logged in. Run kiro-cli login", p.stdout)
            self.assertIn("WARN kiro-cli: 2.40.0. The gate was measured on 2.33.x and 2.34.x", p.stdout)
        finally:
            m.cleanup()

    def test_an_instance_is_checked_too(self):
        r = RealInstance()
        try:
            p = sh(sys.executable, EFFORTKIT, "doctor", "--instance", r.root, env=r.env, check=False)
            self.assertIn("ok   instance toy configs: current", p.stdout)
            self.assertIn("ok   instance toy commit-msg hook: ok", p.stdout)
            (r.root / "overlay/agents/tester.md").write_text("- A new rule.\n")
            p = sh(sys.executable, EFFORTKIT, "doctor", "--instance", r.root, env=r.env, check=False)
            self.assertIn("WARN instance toy configs:", p.stdout)
        finally:
            r.cleanup()


class Setup(unittest.TestCase):
    def test_setup_links_the_command_once_and_keeps_a_foreign_file(self):
        m = Machine()
        try:
            target = m.dir / "home-bin"
            p = m.kit("setup", "--bin", target)
            self.assertIn(f"linked {target}/effortkit -> {core.KIT}/bin/effortkit", p.stdout)
            self.assertIn(f"note: {target} is not on PATH", p.stdout)
            self.assertEqual(core.real(target / "effortkit"), core.real(core.KIT / "bin/effortkit"))
            self.assertIn("links to this kit already", m.kit("setup", "--bin", target).stdout)
            (target / "effortkit").unlink()
            (target / "effortkit").write_text("#!/bin/sh\necho other\n")
            p = m.kit("setup", "--bin", target)
            self.assertEqual(p.returncode, 2)
            self.assertIn("is not the command of this kit", p.stderr)
            self.assertEqual((target / "effortkit").read_text(), "#!/bin/sh\necho other\n")
            m.kit("setup", "--bin", target, "--force")
            self.assertTrue((target / "effortkit").is_symlink())
            env = {**m.env, "PATH": f"{target}{os.pathsep}{m.env['PATH']}"}
            p = sh(sys.executable, EFFORTKIT, "doctor", env=env, check=False, cwd=m.dir)
            self.assertIn(f"ok   effortkit on PATH: {target}/effortkit", p.stdout)
        finally:
            m.cleanup()


if __name__ == "__main__":
    unittest.main()
