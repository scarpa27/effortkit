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


if __name__ == "__main__":
    unittest.main()
