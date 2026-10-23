"""The README names the real commands. A table that drifts from the parser misleads every new user."""
import re
import unittest

from tests.sandbox import KIT
from effortkit import cli, kitcli

# Commands that the owner rarely types. The README may leave them out.
UNLISTED = {"effort snapshot", "effortkit help", "effortkit selftest"}


def subcommands(parser) -> set[str]:
    action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    return {name for name in action.choices if not name.startswith("_")}


class ReadmeCommands(unittest.TestCase):
    def setUp(self):
        self.readme = (KIT / "README.md").read_text(encoding="utf-8")
        self.real = {f"effort {c}" for c in subcommands(cli.parser())} | {f"effortkit {c}" for c in subcommands(kitcli.parser())}

    def test_every_command_in_the_readme_exists(self):
        named = set(re.findall(r"`(effort(?:kit)? [a-z][a-z-]*)", self.readme))
        self.assertEqual(sorted(named - self.real), [])

    def test_every_command_of_the_owner_is_in_the_readme(self):
        named = set(re.findall(r"`(effort(?:kit)? [a-z][a-z-]*)", self.readme))
        self.assertEqual(sorted(self.real - named - UNLISTED), [])


if __name__ == "__main__":
    unittest.main()
