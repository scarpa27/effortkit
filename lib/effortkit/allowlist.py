"""The allowedCommands patterns of the roles with a read-only shell.

kiro-cli matches allowedCommands against the whole command text, so allowlist() joins the simple commands of a role
into one anchored pattern. The word grammar alone keeps "rg x; rm -rf y" out: a character joins a word only where
the shell cannot read it as a chain, pipe, redirect or substitution. Inside "..." only $ and ` expand.
A $ may appear in a word, because "$(" cannot: the "(" is no word character, inside or outside double quotes.
So "$VAR" and $? pass, and the gate resolves or refuses the path. A pattern that needs a bracket goes in single
quotes, where bash expands nothing.
The lists name the commands coarsely, and the gate decides what each call does: a git write, a flag that runs a
program, a path outside the scope of the role. One rule in one place beats two that drift apart.
The Rust engine of kiro-cli has no lookaround. Keep the escapes minimal: the engine refused a needless one before.
"""
from __future__ import annotations

PLAIN = r"""[^\s;&|<>`()'"\\]"""
# Inside "..." a bracket is text, but "$(" starts a command. A $ is allowed only before another character.
DQ = r""""(?:[^"`$\\\n]|\\[^\n]|\$[^("\n])*\""""
WORD = rf"""(?:{PLAIN}|\\[^\n]|'[^'\n]*'|{DQ})+"""
# A redirect of any stream to a file or to another stream. The gate checks the file.
REDIRECT = rf"(?:(?:[0-9]?>>?|&>>?) *{WORD}|[0-9]?>&[0-9-]|[0-9]?<&[0-9-]|2>&1|[0-9]?< *{WORD})"
ARGS = rf"(?: +(?:{REDIRECT}|{WORD}))*"
TIMEOUT = r"timeout +(?:-k +\d+[smh]? +)?\d+[smh]? +"
JOIN = r" *(?:\|\||&&|\||;) *"
# The words that open or close a loop or a condition. The gate judges each command inside them.
BLOCK = rf"(?:for +{PLAIN}+ +in{ARGS}|while|until|if|elif|case{ARGS}|do|done|then|else|fi|esac|\{{|\}}|!)"
ASSIGN = rf"[A-Za-z_][A-Za-z0-9_]*=(?:{WORD})?"

READ_ONLY = [
    # Every git form. The gate refuses the ones that change a repository, and the flags that run a program.
    rf"git{ARGS}",
    rf"(?:rg|grep|cat|head|tail|wc|file|stat|jq|diff|ls|tree|pwd|cd|sort|uniq|cut|tr|du|df|sha256sum|sha1sum|md5sum"
    rf"|realpath|readlink|basename|dirname|date|which|echo|printf|test|\[|sed|awk|find|comm|paste|column|nl|tac"
    rf"|hexdump|od|xxd|strings|xmllint|zcat|zgrep|seq|sleep|ps|nproc|cmp|less|more|true|false|bc|expr|rev|fold"
    # These write, and the gate allows them only in /tmp, the plan folder and the inboxes, as for the write tool.
    rf"|mkdir|rm|cp|mv|touch|tee|unzip|zipinfo){ARGS}",
    # A test suite or a module that only reads. The gate refuses it in a folder where an agent can write code.
    rf"(?:{PLAIN}*/)?python3?(?:\.\d+)?(?: +-[A-Za-z])* +-m +(?:unittest|pytest|zipfile|json\.tool|site|sysconfig|platform){ARGS}",
    rf"kiro-cli +(?:--version|--help|agent +list|agent +validate{ARGS}|settings +list|settings +--help|settings +\w+(?:\.\w+)+)"
    rf"(?: +(?:-f|--format) +\w+)?(?: +{REDIRECT})*",
]
# The forge command line tools. The gate refuses their writes.
FORGE_READ = [rf"glab +{WORD}{ARGS}", rf"gh +{WORD}{ARGS}"]
RESEARCH = [
    rf"pip3? +(?:index +versions|download|show|list){ARGS}",
    rf"npm +(?:view|info|ls|outdated){ARGS}",
    rf"(?:openssl +s_client|getent +hosts|curl +-sI){ARGS}",
]
# The effort commands that only read, or that write one inbox file. The gate refuses the others anyway.
EFFORT_READ = [rf"(?:{PLAIN}*/)?effort +(?:status|find|logs|wait|preflight|help|kb|report|plan-review|improve +stats){ARGS}",
               rf"(?:{PLAIN}*/)?effortkit +(?:check|instances|reports|help){ARGS}"]


def segment(pattern: str) -> str:
    """A configured pattern as one command of the allowlist, with optional redirects after it."""
    return rf"(?:{pattern})(?: +{REDIRECT})*"


def allowlist(*families: list[str]) -> list[str]:
    """The allowedCommands of one role.

    A command text is a chain of segments. A segment is one of the read commands of the role, with its optional
    assignments, timeout and redirects; or the keywords of a loop or a condition; or an assignment.
    The gate judges every command, so the pattern only has to keep out what it cannot see: another program, a
    command substitution and a backtick.
    Measured 2026-10-22 with kiro-cli 2.33.1: with the pattern "^.*$" the shell tool still refuses a heredoc, a
    command substitution and an option such as `rg --pre`. So kiro-cli checks those before allowedCommands.
    """
    cmds = "|".join(p for family in families for p in family)
    one = rf"(?:{ASSIGN} +)*(?:{TIMEOUT})?(?:{cmds})"
    seg = rf"(?:(?:{BLOCK} +)*{one}|{BLOCK}(?: +{BLOCK})*|{ASSIGN})"
    return [rf"^ *{seg}(?:{JOIN}{seg})*(?:{JOIN})? *$"]
