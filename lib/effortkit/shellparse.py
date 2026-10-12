"""Split a shell command text into the simple commands that bash would run.

The gate judges a command by its text. This parser finds every simple command, including the ones inside
command substitutions, loops, conditions and unquoted heredoc bodies. Quoted text and comments are not commands.
tests/test_gate.py covers each form.
"""
from __future__ import annotations

import os
import re
import shlex


# Private-use characters that never occur in a real command. SUBST stands for the output of a command substitution,
# and LITERAL for a $ that bash keeps as text.
SUBST, LITERAL = "\ue025", "\ue024"
SEPARATORS = " \t\n;&|()<>"


class ShellText:
    """Split a command text into its outer text and the texts of its command substitutions.

    bash runs each $(...), `...`, <(...) and >(...), so their texts go to `inner`, and the outer text holds SUBST.
    Single quotes and quoted heredocs are text: their backticks and $ characters are not commands.
    The outer text has no comments, no heredoc bodies and no line continuations.
    """

    def __init__(self, text: str):
        self.t, self.inner, self.pending = text, [], []

    def parse(self) -> str:
        return self.scan(0, None)[0]

    def scan(self, i: int, stop: str | None) -> tuple[str, int]:
        t, out, depth = self.t, [], 0
        while i < len(t):
            ch = t[i]
            if stop == ")" and ch == ")" and depth == 0:
                return "".join(out), i + 1
            if ch == "\\":
                if t.startswith("\\\n", i):
                    i += 2
                else:
                    out.append(LITERAL if t.startswith("\\$", i) else t[i:i + 2])
                    i += 2
            elif ch == "'":
                j = t.find("'", i + 1)
                if j < 0:
                    raise ValueError("an unclosed single quote")
                out.append("'" + t[i + 1:j].replace("$", LITERAL) + "'")
                i = j + 1
            elif ch == '"':
                s, i = self.double(i + 1)
                out.append('"' + s + '"')
            elif ch == "$":
                s, i = self.dollar(i)
                out.append(s)
            elif ch == "`":
                i = self.backtick(i + 1)
                out.append(SUBST)
            elif ch in "<>" and t.startswith("(", i + 1):
                _, j = self.scan(i + 2, ")")
                self.inner.append(t[i + 2:j - 1])
                out.append(SUBST)
                i = j
            elif t.startswith("<<", i) and not t.startswith("<<<", i):
                s, i = self.heredoc_marker(i)
                out.append(s)
            elif ch == "#" and (not out or out[-1][-1:] in SEPARATORS):
                j = t.find("\n", i)
                i = len(t) if j < 0 else j
            elif ch == "\n":
                out.append("\n")
                i = self.bodies(i + 1)
            else:
                if stop == ")":
                    depth += {"(": 1, ")": -1}.get(ch, 0)
                out.append(ch)
                i += 1
        if stop:
            raise ValueError("an unclosed $(")
        return "".join(out), i

    def double(self, i: int) -> tuple[str, int]:
        t, out = self.t, []
        while i < len(t):
            ch = t[i]
            if ch == '"':
                return "".join(out), i + 1
            if ch == "\\" and i + 1 < len(t):
                if t[i + 1] != "\n":
                    out.append(LITERAL if t[i + 1] == "$" else t[i:i + 2])
                i += 2
            elif ch == "$":
                s, i = self.dollar(i, in_dq=True)
                out.append(s)
            elif ch == "`":
                i = self.backtick(i + 1)
                out.append(SUBST)
            else:
                out.append(ch)
                i += 1
        raise ValueError("an unclosed double quote")

    def dollar(self, i: int, in_dq: bool = False) -> tuple[str, int]:
        t = self.t
        if t.startswith("$((", i):
            depth, j = 2, i + 3
            while j < len(t) and depth:
                depth += {"(": 1, ")": -1}.get(t[j], 0)
                j += 1
            if depth:
                raise ValueError("an unclosed $((")
            self.expansions(t[i + 3:j - 2])
            return SUBST, j
        if t.startswith("$(", i):
            _, j = self.scan(i + 2, ")")
            self.inner.append(t[i + 2:j - 1])
            return subst_value(t[i + 2:j - 1]), j
        if t.startswith("${", i):
            depth, j = 1, i + 2
            while j < len(t) and depth:
                depth += {"{": 1, "}": -1}.get(t[j], 0)
                j += 1
            if depth:
                raise ValueError("an unclosed ${")
            before = len(self.inner)
            self.expansions(t[i + 2:j - 1])
            return (SUBST if len(self.inner) > before else t[i:j]), j
        if t.startswith("$'", i) and not in_dq:
            j = i + 2
            while j < len(t) and t[j] != "'":
                j += 2 if t[j] == "\\" else 1
            if j >= len(t):
                raise ValueError("an unclosed $'")
            return "'" + t[i + 2:j].replace("$", LITERAL) + "'", j + 1
        if t.startswith('$"', i) and not in_dq:
            return "", i + 1
        return "$", i + 1

    def backtick(self, i: int) -> int:
        t, buf = self.t, []
        while i < len(t):
            ch = t[i]
            if ch == "\\" and i + 1 < len(t) and t[i + 1] in "`\\$":
                buf.append(t[i + 1])
                i += 2
            elif ch == "`":
                self.inner.append("".join(buf))
                return i + 1
            else:
                buf.append(ch)
                i += 1
        raise ValueError("an unclosed backtick")

    def expansions(self, text: str) -> None:
        """Collect the command substitutions of a text in which quotes are plain characters, as in a heredoc body."""
        sub, i = ShellText(text), 0
        while i < len(text):
            if text[i] == "\\":
                i += 2
            elif text.startswith(("$(", "${"), i):
                i = sub.dollar(i, in_dq=True)[1]
            elif text[i] == "`":
                i = sub.backtick(i + 1)
            else:
                i += 1
        self.inner += sub.inner

    def heredoc_marker(self, i: int) -> tuple[str, int]:
        t, j = self.t, i + 2
        strip = t.startswith("-", j)
        j += strip
        while j < len(t) and t[j] in " \t":
            j += 1
        word, quoted = [], False
        while j < len(t) and t[j] not in SEPARATORS:
            if t[j] in "'\"":
                k = t.find(t[j], j + 1)
                if k < 0:
                    raise ValueError("an unclosed quote in a heredoc marker")
                word.append(t[j + 1:k])
                quoted, j = True, k + 1
            elif t[j] == "\\" and j + 1 < len(t):
                word.append(t[j + 1])
                quoted, j = True, j + 2
            else:
                word.append(t[j])
                j += 1
        if word:
            self.pending.append(("".join(word), quoted, strip))
        return "<< HEREDOC ", j

    def bodies(self, i: int) -> int:
        """Skip the heredoc bodies that start after this line. An unquoted body still runs its substitutions."""
        t = self.t
        while self.pending:
            delim, quoted, strip = self.pending.pop(0)
            lines = []
            while i < len(t):
                j = t.find("\n", i)
                line, i = (t[i:], len(t)) if j < 0 else (t[i:j], j + 1)
                if (line.lstrip("\t") if strip else line) == delim:
                    break
                lines.append(line)
            if not quoted:
                self.expansions("\n".join(lines))
        return i


def subst_value(inner: str) -> str:
    """What the gate knows about the output of $(inner): the folder of a mktemp result, else nothing."""
    try:
        w = shlex.split(inner)
    except ValueError:
        return SUBST
    if not w or os.path.basename(w[0]) != "mktemp" or any(c in inner for c in ";&|$`\n"):
        return SUBST
    args, tmpdir, use_tmp, template, k = w[1:], None, False, None, 0
    while k < len(args):
        a = args[k]
        if a == "-p" and k + 1 < len(args):
            tmpdir, k = args[k + 1], k + 2
            continue
        if a.startswith("--tmpdir="):
            tmpdir = a.split("=", 1)[1]
        elif a in ("-t", "--tmpdir"):
            use_tmp = True
        elif not a.startswith("-"):
            template = a
        k += 1
    if template and template.startswith("/"):
        return os.path.dirname(template) + "/" + SUBST
    if tmpdir or use_tmp or not template:
        return (tmpdir or os.environ.get("TMPDIR") or "/tmp").rstrip("/") + "/" + SUBST
    return SUBST


def _unquoted_newlines_to_semicolons(cmd: str) -> str:
    out, quote, i = [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == "\\" and quote != "'" and i + 1 < len(cmd):
            out.append(cmd[i:i + 2])
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = ";"
        out.append(ch)
        i += 1
    return "".join(out)


CONTROL = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;", ";&"}
REDIRECT_OUT = {">", ">>", ">|", "&>", "&>>"}
REDIRECT_OTHER = {"<", "<<", "<<<", "<&", ">&", "<>"}


def split_commands(cmd: str) -> list[dict]:
    """Return simple commands as {words, out} dicts. Raise ValueError when the text does not parse."""
    return split_outer(ShellText(cmd).parse())


def split_outer(text: str) -> list[dict]:
    lex = shlex.shlex(_unquoted_newlines_to_semicolons(text), posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    # ShellText removed the comments. A # inside a word, as in a URL fragment, is text.
    lex.commenters = ""
    tokens = list(lex)
    cmds, cur = [], {"words": [], "out": []}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in CONTROL:
            if cur["words"] or cur["out"]:
                cmds.append(cur)
            cur = {"words": [], "out": []}
        elif t in REDIRECT_OUT or t in REDIRECT_OTHER:
            if cur["words"] and cur["words"][-1].isdigit():
                cur["words"].pop()
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            if t in REDIRECT_OUT and target and not target.startswith("&"):
                cur["out"].append(target)
            i += 1
        else:
            cur["words"].append(t)
        i += 1
    if cur["words"] or cur["out"]:
        cmds.append(cur)
    return cmds


WRAPPERS = {"env", "time", "nice", "nohup", "stdbuf", "command", "builtin", "exec", "timeout"}
# A command can follow these words in the same simple command, as in "do rm -rf x". The gate judged "do" as the verb
# before, so it never saw the rm.
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}", "done", "fi", "esac"}
# These start a list of words that bash does not run: for NAME in WORDS, case WORD in, select NAME in WORDS.
NOT_COMMANDS = {"for", "case", "select", "in"}


def strip_prefix(words: list[str]) -> list[str]:
    """Remove keywords, variable assignments and wrapper commands, so the first word is the real verb."""
    w = list(words)
    while w:
        head = w[0]
        if head in KEYWORDS:
            w.pop(0)
        elif head in NOT_COMMANDS:
            return []
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            w.pop(0)
        elif head in WRAPPERS:
            w.pop(0)
            while w and (w[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[0])
                         or (head == "timeout" and re.match(r"^\d+[smhd]?$", w[0]))
                         or (head == "nice" and re.match(r"^-?\d+$", w[0]))):
                w.pop(0)
        else:
            break
    return w

