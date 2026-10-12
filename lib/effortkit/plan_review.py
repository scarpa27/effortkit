"""Build a Lavish review page from an effort's task.md and questions.md.

The supervisor opens the page with lavish-axi, and the owner answers each question, comments on each
section of the plan, and sends the answers back. The approval itself stays `effort approve`, because a
prompt from a page reaches the agent, and an agent must never approve its own plan.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from . import core as na

QUESTION = re.compile(r"^##\s+(Q\d+|[A-Z][A-Za-z0-9-]*\d+)\s*:\s*(.+)$")
FIELD = re.compile(r"^(Recommended|Depends on|Why|Options)\s*:\s*(.*)$", re.I)


def parse_questions(text: str) -> list[dict]:
    """questions.md holds '## Q1: <question>' blocks with 'Recommended:', 'Depends on:' and 'Why:' lines."""
    if text.strip() == "NO_QUESTIONS":
        return []
    out, cur, field = [], None, None
    for line in text.splitlines():
        m = QUESTION.match(line)
        if m:
            cur = {"id": m.group(1), "q": m.group(2).strip(), "recommended": "", "depends": "", "why": "", "options": ""}
            out.append(cur)
            field = None
            continue
        if cur is None:
            continue
        f = FIELD.match(line.strip())
        if f:
            field = {"recommended": "recommended", "depends on": "depends", "why": "why", "options": "options"}[f.group(1).lower()]
            cur[field] = f.group(2).strip()
        elif field and line.strip():
            cur[field] = (cur[field] + "\n" + line.strip()).strip()
    return out


def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)


DECISION = re.compile(r"^(Q\d+|[A-Z][A-Za-z0-9-]*\d+)\s*:\s*(.+)$")
OPTION_BULLET = re.compile(r"^\s*[-*]\s+(?:\(([A-Za-z])\)|Option\s+([A-Z])\s*[:.)]|([A-Z])\s*[:.)])\s+(.+)$")
OPTION_LABEL = re.compile(r"^([A-Z])\s*[:.)]\s*(.+)$")
RECOMMENDED = re.compile(r"^\s*(?:[-*]\s+)?Recommend(?:ed|ation)(?:\s+of\s+[^:]+)?\s*:\s*(.+?)\.?\s*$", re.I)


def parse_options(body: str) -> list[tuple[str, str]]:
    """The options of a decision: '- (a) ...' or '- A: ...' bullets, or else the first column of its first table."""
    bullets, open_bullet = [], False
    for line in body.splitlines():
        m = OPTION_BULLET.match(line)
        if m:
            bullets.append((next(g for g in m.groups()[:3] if g).upper(), m.group(4).strip()))
            open_bullet = True
        elif open_bullet and line.startswith(("  ", "\t")) and line.strip() and not re.match(r"^\s*([-*]|\d+\.)\s+", line):
            bullets[-1] = (bullets[-1][0], bullets[-1][1] + " " + line.strip())
        else:
            open_bullet = False
    if len(bullets) >= 2:
        return bullets
    rows = []
    for line in body.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.match(r"^:?-+:?$", c) for c in cells if c):
                rows.append(cells[0])
        elif rows:
            break
    out = []
    for n, label in enumerate(rows[1:]):
        m = OPTION_LABEL.match(label)
        out.append((m.group(1), m.group(2).strip()) if m else (chr(ord("A") + n), label))
    return out if len(out) >= 2 else []


def recommended_key(rec: str, options: list[tuple[str, str]]) -> str:
    """Match 'A', '(a)', '24 h' or the start of an option text to the key of that option."""
    keys = {k for k, _ in options}
    m = re.match(r"^\(?([A-Za-z])\)?$", rec.strip())
    if m and m.group(1).upper() in keys:
        return m.group(1).upper()
    low = rec.strip().lower().rstrip(".")
    for k, label in options:
        lab = label.lower().rstrip(".")
        if low and (lab == low or lab.startswith(low) or low.startswith(lab)):
            return k
    return ""


def parse_doc(text: str) -> list[dict]:
    """Split a plan file at '## ' headings. A heading such as '## D8: <title>' with two or more options is a decision."""
    out = []
    for title, body in sections(text):
        m = DECISION.match(title)
        options = parse_options(body) if m else []
        if not options:
            out.append({"kind": "section", "title": title, "body": body})
            continue
        rec = next((r.group(1) for r in map(RECOMMENDED.match, body.splitlines()) if r), "")
        out.append({"kind": "decision", "id": m.group(1), "title": m.group(2).strip(), "body": body,
                    "options": options, "rec_text": rec, "rec": recommended_key(rec, options)})
    return out


def render_md(text: str) -> str:
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append('<pre class="bg-base-200 rounded-box p-3 overflow-x-auto text-sm"><code>'
                       + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1)) + 1
            out.append(f'<h{level} class="font-bold mt-4">{inline(m.group(2))}</h{level}>')
        elif line.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.match(r"^:?-+:?$", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            out.append('<div class="overflow-x-auto"><table class="table table-sm"><thead><tr>'
                       + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table></div>")
            continue
        elif re.match(r"^\s*([-*]|\d+\.)\s+", line):
            tag = "ol" if re.match(r"^\s*\d+\.", line) else "ul"
            items = []
            while i < len(lines):
                if re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                    items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                elif lines[i].startswith(("  ", "\t")) and lines[i].strip():
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            cls = "list-decimal" if tag == "ol" else "list-disc"
            out.append(f'<{tag} class="{cls} ml-6">' + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
        i += 1
    return "\n".join(out)


def sections(text: str) -> list[tuple[str, str]]:
    """Split task.md at '## ' headings. The text before the first heading is the introduction."""
    parts, title, buf = [], "Introduction", []
    for line in text.splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                parts.append((title, "\n".join(buf)))
            title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        parts.append((title, "\n".join(buf)))
    return [(t, s) for t, s in parts
            if not (t == "Introduction" and all(l.startswith("#") or not l.strip() for l in s.splitlines()))]


HEAD = """<!doctype html>
<html lang="en" data-theme="luxury" data-lavish-annotate="off">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/daisyui@5.5.19/daisyui.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/daisyui@5.5.19/themes.css">
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.2.4/dist/index.global.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  :where(p, li, td, th, h1, h2, h3, h4) {{ overflow-wrap: anywhere; }}
  html, body {{ background: var(--color-base-100); color: var(--color-base-content); }}
  code {{ background: var(--color-base-300); padding: .05em .35em; border-radius: .3em; font-size: .88em; }}
  pre code {{ background: transparent; padding: 0; }}
</style></head>
<body><main class="mx-auto max-w-5xl p-4 lg:p-8 space-y-8">
"""

SCRIPT = r"""
<script>
(function () {
  function state(f, text, cls) { var s = f.querySelector('[data-state]'); s.textContent = text; s.className = 'badge badge-sm ' + cls; }
  function prompt(f) {
    var d = new FormData(f), key = f.dataset.lavishQuestion, title = f.dataset.title;
    if (f.dataset.kind === 'choice') {
      var pick = d.get(key + '-choice'), own = String(d.get(key + '-other') || '').trim();
      var remark = String(d.get(key + '-note') || '').trim(), rec = f.dataset.rec || '';
      var input = f.querySelector('input[name="' + key + '-choice"]:checked'), label = input ? input.dataset.label : '';
      var said;
      if (pick === 'other') { if (!own) return null; said = 'own answer: ' + own; }
      else if (pick) { said = 'option ' + pick + ' (' + label + ')' + (pick === rec ? ', the recommendation' : ''); }
      else { if (!remark) return null; said = 'no option chosen'; }
      return { text: key + ' "' + title + '": ' + said + (remark ? '. Comment: ' + remark : ''),
               opts: { tag: 'answer', text: key + ': ' + (pick === 'other' ? 'own answer' : pick ? 'option ' + pick : 'comment'),
                       data: { question: key, title: title, choice: pick || '', label: pick === 'other' ? '' : label,
                               answer: pick === 'other' ? own : label, accepted_recommendation: !!pick && pick === rec, comment: remark } } };
    }
    if (f.dataset.kind === 'question') {
      var choice = d.get(key + '-choice'), other = String(d.get(key + '-other') || '').trim();
      var note = String(d.get(key + '-note') || '').trim();
      var answer = choice === 'recommended' ? f.dataset.rec : other;
      if (!answer && !note) return null;
      return { text: key + ' "' + title + '": ' + (choice === 'recommended' ? 'accept the recommendation: ' : 'answer: ') + answer + (note ? '. Comment: ' + note : ''),
               opts: { tag: 'answer', text: key + (choice === 'recommended' ? ': recommended' : ': own answer'),
                       data: { question: key, title: title, answer: answer, accepted_recommendation: choice === 'recommended', comment: note } } };
    }
    var c = String(d.get(key) || '').trim();
    if (!c) return null;
    return { text: 'Comment on the plan section "' + title + '": ' + c, opts: { tag: 'comment', text: 'Comment: ' + title, data: { section: title, comment: c } } };
  }
  function queue(f) {
    var p = prompt(f);
    if (!p) { state(f, 'Nothing to send', 'badge-warning'); return false; }
    if (!(window.lavish && window.lavish.queuePrompt)) { state(f, 'Lavish is not running: use Copy all answers', 'badge-error'); return false; }
    p.opts.element = f; p.opts.queueKey = f.dataset.lavishQuestion;
    window.lavish.queuePrompt(p.text, p.opts); f.dataset.queued = '1'; state(f, 'Queued', 'badge-success'); return true;
  }
  document.addEventListener('submit', function (ev) { var f = ev.target.closest('form[data-kind]'); if (!f) return; ev.preventDefault(); queue(f); });
  document.addEventListener('input', function (ev) { var f = ev.target.closest('form[data-kind]'); if (f && f.dataset.queued === '1') { f.dataset.queued = '2'; state(f, 'Changed since queued: queue again', 'badge-warning'); } });
  window.queueAll = function (btn) {
    var n = 0; document.querySelectorAll('form[data-kind="question"], form[data-kind="choice"]').forEach(function (f) { if (f.dataset.queued !== '1' && queue(f)) n++; });
    btn.nextElementSibling.textContent = n + ' answers queued. Now press Send to Agent.';
  };
  window.copyAll = async function (btn) {
    var out = [];
    document.querySelectorAll('form[data-kind]').forEach(function (f) { var p = prompt(f); if (p) out.push(p.text); });
    var text = out.join('\n\n'), s = btn.nextElementSibling;
    if (!text) { s.textContent = 'Nothing to copy yet.'; return; }
    try { await navigator.clipboard.writeText(text); s.textContent = 'Copied.'; }
    catch (e) { var t = document.createElement('textarea'); t.className = 'textarea w-full'; t.rows = 10; t.value = text; btn.parentElement.after(t); t.select(); s.textContent = 'Copy the text below.'; }
  };
})();
</script>
"""


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def question_card(q: dict) -> str:
    k = esc(q["id"])
    rec = esc(q["recommended"] or "(no recommendation)")
    extra = "".join(f'<p class="text-sm opacity-80"><b>{label}:</b> {inline(q[f])}</p>'
                    for label, f in (("Why", "why"), ("The safe answer depends on", "depends"), ("Options", "options")) if q[f])
    return f"""<form class="card card-border bg-base-200" data-kind="question" data-lavish-question="{k}" data-title="{esc(q['q'])}" data-rec="{rec}">
<div class="card-body gap-3"><div class="flex gap-2 items-start"><span class="badge badge-neutral">{k}</span><h3 class="font-bold">{inline(q['q'])}</h3></div>
{extra}
<label class="flex gap-2 items-start"><input type="radio" class="radio radio-primary radio-sm mt-1" name="{k}-choice" value="recommended" checked>
<span><b>Accept the recommendation:</b> {inline(q['recommended'] or '(none)')}</span></label>
<label class="flex gap-2 items-start"><input type="radio" class="radio radio-sm mt-1" name="{k}-choice" value="other"><span><b>My own answer:</b></span></label>
<textarea class="textarea w-full" name="{k}-other" rows="2" placeholder="Your answer, when you do not accept the recommendation"></textarea>
<textarea class="textarea w-full" name="{k}-note" rows="2" placeholder="Comment (optional)"></textarea>
<div class="flex gap-2 items-center"><button class="btn btn-sm btn-primary" type="submit">Queue answer</button><span data-state class="badge badge-sm badge-ghost">Not queued</span></div>
</div></form>"""


def comment_form(title: str, n: int) -> str:
    key = f"S{n}"
    return f"""<form class="rounded-box bg-base-200 p-3" data-kind="comment" data-lavish-question="{key}" data-title="{esc(title)}">
<textarea class="textarea w-full" name="{key}" rows="2" placeholder="Comment on '{esc(title)}' (optional)"></textarea>
<div class="flex gap-2 items-center mt-2"><button class="btn btn-sm" type="submit">Queue comment</button><span data-state class="badge badge-sm badge-ghost">Not queued</span></div></form>"""


def choice_card(d: dict) -> str:
    k = esc(d["id"])
    radios = []
    for key, label in d["options"]:
        rec = key == d["rec"]
        badge = ' <span class="badge badge-primary badge-sm">recommended</span>' if rec else ""
        radios.append(f'<label class="flex gap-2 items-start"><input type="radio" class="radio radio-sm mt-1{" radio-primary" if rec else ""}" '
                      f'name="{k}-choice" value="{esc(key)}" data-label="{esc(label)}"{" checked" if rec else ""}>'
                      f'<span><b>{esc(key)}:</b> {inline(label)}{badge}</span></label>')
    radios.append(f'<label class="flex gap-2 items-start"><input type="radio" class="radio radio-sm mt-1" name="{k}-choice" '
                  f'value="other" data-label="own answer"><span><b>My own answer</b></span></label>')
    rec_note = "" if d["rec"] or not d["rec_text"] else \
        f'<p class="text-sm"><b>Recommendation:</b> {inline(d["rec_text"])}</p>'
    return f"""<form class="card card-border bg-base-200" data-kind="choice" data-lavish-question="{k}" data-title="{esc(d['title'])}" data-rec="{esc(d['rec'])}">
<div class="card-body gap-3"><div class="flex gap-2 items-start"><span class="badge badge-neutral">{k}</span><h3 class="font-bold">{inline(d['title'])}</h3></div>
<div class="space-y-2">{render_md(d['body'])}</div>{rec_note}
<fieldset class="space-y-2"><legend class="font-bold text-sm mb-1">Your choice for {k}</legend>{''.join(radios)}</fieldset>
<textarea class="textarea w-full" name="{k}-other" rows="2" aria-label="My own answer for {k}" placeholder="Your answer, when no option fits"></textarea>
<textarea class="textarea w-full" name="{k}-note" rows="2" aria-label="Comment on {k}" placeholder="Comment (optional)"></textarea>
<div class="flex gap-2 items-center"><button class="btn btn-sm btn-primary" type="submit">Queue answer</button><span data-state class="badge badge-sm badge-ghost">Not queued</span></div>
</div></form>"""


def generate(e: na.Effort, doc: str = "task.md") -> Path:
    if doc != "task.md":
        return generate_doc(e, doc)
    task = (e.plan / "task.md").read_text(encoding="utf-8") if (e.plan / "task.md").exists() else ""
    qtext = (e.plan / "questions.md").read_text(encoding="utf-8") if (e.plan / "questions.md").exists() else "NO_QUESTIONS"
    qs = parse_questions(qtext)
    title = next((l.lstrip("# ").strip() for l in task.splitlines() if l.startswith("#")), f"Plan of {e.name}")
    body = [HEAD.format(title=esc(f"{e.name}: plan review")),
            f'<header class="space-y-2"><span class="badge badge-primary badge-soft">Plan review</span>'
            f'<h1 class="text-2xl font-bold">{inline(title)}</h1>'
            f'<p class="text-sm opacity-80">Effort <code>{esc(e.name)}</code> ({esc(e.kind)}). Answer the questions, comment on any section, '
            f'then press Send to Agent in the Lavish panel. This page does not approve the plan. Approve it with '
            f'<code>!effort approve {esc(e.name)}</code> when the plan is final.</p></header>']
    if qs:
        body.append('<section class="space-y-4"><h2 class="text-xl font-bold">Questions from the planner</h2>')
        body += [question_card(q) for q in qs]
        body.append('<div class="flex gap-2 items-center"><button class="btn btn-primary btn-sm" type="button" onclick="queueAll(this)">'
                    'Queue every answer</button><span class="text-sm"></span></div></section>')
    elif qtext.strip() != "NO_QUESTIONS":
        body.append('<section><h2 class="text-xl font-bold">questions.md</h2><p class="text-sm">The file has no '
                    "'## Q1: ...' blocks, so it shows as text.</p>" + render_md(qtext) + "</section>")
    body.append('<section class="space-y-4"><h2 class="text-xl font-bold">The plan (task.md)</h2>')
    for n, (stitle, stext) in enumerate(sections(task), 1):
        body.append(f'<article class="card card-border"><div class="card-body gap-2"><h3 class="text-lg font-bold">{inline(stitle)}</h3>'
                    f"{render_md(stext)}{comment_form(stitle, n)}</div></article>")
    body.append('</section><section><div class="flex gap-2 items-center"><button class="btn btn-sm" type="button" onclick="copyAll(this)">'
                'Copy all answers</button><span class="text-sm"></span></div><p class="text-xs opacity-70 mt-2">Without Lavish: copy, '
                'then paste the text into the chat.</p></section></main>' + SCRIPT + "</body></html>")
    out = e.plan / "review" / f"plan-review-{na.stamp()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(body), encoding="utf-8")
    return out


def generate_doc(e: na.Effort, doc: str) -> Path:
    """Review page for another plan file, for example decision.md: one card per decision, a comment box per section."""
    src = na.real(e.plan / doc)
    if not (na.within(src, na.real(e.plan)) and src.suffix == ".md" and src.is_file()):
        raise ValueError(f"{doc} is not a Markdown file in {e.plan}")
    text = src.read_text(encoding="utf-8")
    items = parse_doc(text)
    decisions = [d for d in items if d["kind"] == "decision"]
    title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), f"{src.name} of {e.name}")
    what = "Decision review" if src.name == "decision.md" else "Review"
    body = [HEAD.format(title=esc(f"{e.name}: {src.name}")),
            f'<header class="space-y-2"><span class="badge badge-primary badge-soft">{what}</span>'
            f'<h1 class="text-2xl font-bold">{inline(title)}</h1>'
            f'<p class="text-sm opacity-80">Effort <code>{esc(e.name)}</code> ({esc(e.kind)}), file <code>{esc(src.name)}</code>. '
            f'{"Choose an option for each decision. " if decisions else ""}Comment on any section, then press Send to Agent '
            f'in the Lavish panel. The supervisor records your answers word for word.</p></header>']
    n = 0
    for d in items:
        if d["kind"] == "decision":
            body.append(choice_card(d))
        else:
            n += 1
            body.append(f'<article class="card card-border"><div class="card-body gap-2"><h2 class="text-lg font-bold">{inline(d["title"])}</h2>'
                        f'{render_md(d["body"])}{comment_form(d["title"], n)}</div></article>')
    if decisions:
        body.append('<div class="flex gap-2 items-center"><button class="btn btn-primary btn-sm" type="button" onclick="queueAll(this)">'
                    'Queue every answer</button><span class="text-sm"></span></div>')
    body.append('<section><div class="flex gap-2 items-center"><button class="btn btn-sm" type="button" onclick="copyAll(this)">'
                'Copy all answers</button><span class="text-sm"></span></div><p class="text-xs opacity-70 mt-2">Without Lavish: copy, '
                'then paste the text into the chat.</p></section></main>' + SCRIPT + "</body></html>")
    out = e.plan / "review" / f"{src.stem}-review-{na.stamp()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(body), encoding="utf-8")
    return out
