"""The parts of the core that need no instance: the rules that the kit derives from the documented test commands."""
import re
import unittest

from tests.sandbox import KIT  # noqa: F401  (puts lib/ on sys.path)
from effortkit import core


def runs(template: str, cmd: str) -> bool:
    return bool(re.fullmatch(core.command_pattern(template), cmd))


class TestCommandRules(unittest.TestCase):
    def test_a_placeholder_is_one_word_and_flags_go_anywhere(self):
        t = "mvn -pl <module> -am test"
        for cmd in ("mvn -pl core -am test", "mvn -q -pl core -am test", "mvn -pl core -am test -Dtest=FooTest",
                    "mvn -pl core -am test -Dtest=FooTest -Dsurefire.failIfNoSpecifiedTests=false"):
            self.assertTrue(runs(t, cmd), cmd)
        for cmd in ("mvn -pl core -am test install", "mvn -pl core -am install", "mvn -pl core test",
                    "mvn -pl a b -am test", "mvn -pl core -am test; rm -rf x"):
            self.assertFalse(runs(t, cmd), cmd)

    def test_plain_commands_and_placeholders_inside_a_word(self):
        self.assertTrue(runs("make test", "make test"))
        self.assertFalse(runs("make test", "make test deploy"))
        self.assertTrue(runs("python3 -m pytest <path>", "python3 -m pytest -x tests/test_a.py -q"))
        self.assertFalse(runs("python3 -m pytest <path>", "python3 -m pytest a.py b.py"))
        self.assertTrue(runs("go test <pkg>", "go test ./..."))
        self.assertTrue(runs("mvn test -Dtest=<Class>", "mvn test -Dtest=FooTest"))
        self.assertFalse(runs("mvn test -Dtest=<Class>", "mvn test -Dother=FooTest"))
        self.assertTrue(runs("npm test -- <path>", "npm test -- src/a.test.js"))

    def test_meta_characters_are_literal(self):
        self.assertTrue(runs("./gradlew test", "./gradlew test"))
        self.assertFalse(runs("./gradlew test", "x/gradlew test"))
        self.assertTrue(runs("tox -e py312", "tox -e py312"))
        # Only the meta characters are escaped. A needless escape broke an allowlist of kiro-cli before.
        self.assertEqual(core.command_pattern("a-b c=d e/f"), r"a-b(?: -\S+)* c=d(?: -\S+)* e/f(?: -\S+)*")

    def test_explicit_patterns_add_to_the_derived_ones(self):
        cfg = {"tests": {"commands": ["make test"], "patterns": [r"tox(?: -e \S+)?"]}}
        self.assertEqual(core.test_patterns(cfg), [core.command_pattern("make test"), r"tox(?: -e \S+)?"])


class TestInbox(unittest.TestCase):
    def setUp(self):
        from tests.sandbox import FakeInstance
        self.r = FakeInstance()
        self.inst = self.r.inst

    def tearDown(self):
        self.r.cleanup()

    def test_the_type_line_decides_and_a_missing_one_is_inferred(self):
        from effortkit import inbox
        box = self.inst.inbox
        (box / "20261026T080000Z-e1-explorer.md").write_text("type: fact\ntopic: build\n\nThe build needs Java 25.\n")
        (box / "20261026T080001Z-e1-reviewer.md").write_text("scope: kit\nseverity: blocker\n\n## What happened\nx\n")
        (box / "20261026T080002Z-e1-tester.md").write_text("topic: testing\n\nThe suite is slow.\n")
        (box / "20261026T080003Z-e1-debugger.md").write_text("Just text.\n")
        got = {n.name: (n.type, n.effort, n.role) for n in inbox.notes(self.inst)}
        self.assertEqual(got, {"20261026T080000Z-e1-explorer.md": ("fact", "e1", "explorer"),
                               "20261026T080001Z-e1-reviewer.md": ("workflow", "e1", "reviewer"),
                               "20261026T080002Z-e1-tester.md": ("fact", "e1", "tester"),
                               "20261026T080003Z-e1-debugger.md": ("unknown", "e1", "debugger")})
        self.assertEqual([n.name for n in inbox.facts_of(self.inst, "e1")],
                         ["20261026T080000Z-e1-explorer.md", "20261026T080002Z-e1-tester.md"])

    def test_two_notes_in_one_second_get_two_files(self):
        from effortkit import inbox
        a = inbox.write(self.inst, "fact", {"topic": "build"}, "One.", "e1", "explorer")
        b = inbox.write(self.inst, "fact", {"topic": "build"}, "Two.", "e1", "explorer")
        self.assertNotEqual(a, b)
        self.assertEqual({n.effort for n in inbox.notes(self.inst)}, {"e1"})
        with self.assertRaises(ValueError):
            inbox.write(self.inst, "idea", {}, "x")


if __name__ == "__main__":
    unittest.main()
