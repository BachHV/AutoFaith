"""Draw the proof graphs in a tactic-roles out.json.

    python3 FLproof/graph.py out.json            # writes out.html next to out.json
    python3 FLproof/graph.py out.json -o g.html  # choose the output file
    python3 FLproof/graph.py out.json --dot DIR  # also keep one .dot file per proof
    python3 FLproof/graph.py out.json --png DIR  # also write one .png image per proof
    python3 FLproof/graph.py out.json --cases order   # default view: steps in source order

Cases: when a step leaves several goals (`constructor`, `rcases ... with h | h`,
`induction`, `interval_cases`, `refine ⟨?_, ?_⟩`, ...), the steps after it are
matched to the goal they work on. Two views:
  - split (default): each goal gets its own "case k" block with the steps that
    solve it, side by side.
  - order: one chain in the order the steps appear in the source.
The HTML page contains both; a toggle above each proof switches between them.
`--cases` picks which one is shown first and which one the .png/.dot files use.

Each proof is drawn top to bottom, alternating two kinds of node:
  - a proof state (white box): the goals, with the hypotheses that are new
    since the previous state (+) or that changed (~, e.g. after `rw ... at h`).
    Hover a state to see all of its hypotheses.
  - a tactic (blue box): the tactic text and its syntax kind. A `rw`/`simp`
    with several rules (or an `at h`) also lists its rules, numbered.
A green state means no goals are left. A `have ... := by ...` or `calc` step
with its own proof gets that proof drawn beside it (dashed, "aux proof k"),
and nested steps are drawn the same way (dotted, "substeps").

Needs Graphviz (`brew install graphviz`) for the `dot` command.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

WRAP = 70          # characters per line inside a node
MAX_TACTIC_LINES = 4


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def wrap(s: str, width: int = WRAP) -> list[str]:
    out: list[str] = []
    for line in s.splitlines() or [""]:
        out.extend(textwrap.wrap(line, width, subsequent_indent="    ",
                                 break_long_words=True, replace_whitespace=False) or [""])
    return out


def hyp_str(h: dict) -> str:
    # Local definitions (`let b := a + a`, `set y := x + 1`) carry their value.
    value = f" := {h['value']}" if h.get("value") else ""
    return f"{h['name']} : {h['type']}{value}"


# Tactics that take a list of rules `[a, ← b, c x]`: the results they rewrite or
# simplify with. Pantograph's `usedConstants` misses most of them (for
# `rw [a, b, c]` it records only `a`, and local hypotheses never), so they are
# read from the tactic text instead.
RULE_TACTICS = ("rw", "rwa", "rewrite", "erw", "nth_rw", "nth_rewrite", "simp", "simp_all",
                "simpa", "dsimp", "simp_rw", "field_simp", "norm_num", "push_cast")


def rewrite_rules(tactic: str) -> tuple[list[str], str]:
    """The rules in `rw [a, b] at h` and similar: (["a", "b"], "h")."""
    text = tactic.strip()
    head = text.split(None, 1)[0] if text else ""
    if head.rstrip("!?") not in RULE_TACTICS:
        return [], ""
    start = text.find("[")
    if start < 0:
        return [], ""
    rules, depth, cur = [], 0, ""
    for i, ch in enumerate(text[start + 1:], start + 1):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")}⟩" or (ch == "]" and depth):
            depth -= 1
        elif ch == "]":
            rules.append(cur.strip())
            loc = text[i + 1:].strip()
            return [r for r in rules if r], loc[3:].strip() if loc.startswith("at ") else ""
        elif ch == "," and depth == 0:
            rules.append(cur.strip())
            cur = ""
            continue
        cur += ch
    return [], ""


# ---------------------------------------------------------------------------
# Goal tracking: turn a flat list of steps into a tree of cases
# ---------------------------------------------------------------------------

@dataclass
class Branch:
    """The steps that solve one goal (a case), starting from `goals`."""
    goals: list[dict]
    steps: list[StepNode] = field(default_factory=list)


@dataclass
class StepNode:
    cp: dict
    cases: list[Branch] = field(default_factory=list)  # set when the step splits its goal


def case_tree(steps: list[dict]) -> list[Branch]:
    """Assign each step to the goal it works on.

    tactic-roles records, for each step, only the goals it acted on
    (`goalsBefore`) and what they became (`goalsAfter`). We keep a stack of the
    open goals, each tagged with the branch that is solving it. A step is put in
    the branch of the first goal it acts on. If it turns that goal into several
    new goals, each new goal starts its own case branch. A step whose goal isn't
    open at all (e.g. the second alternative of `induction ... with`) starts a
    new top-level branch, so the result can have more than one branch.
    """
    top: list[Branch] = []
    stack: list[tuple[dict, Branch]] = []
    for cp in steps:
        before, after = cp["goalsBefore"], cp["goalsAfter"]
        i = next((k for k, (g, _) in enumerate(stack) if before and g == before[0]), None)
        if i is None:
            br = Branch(before)
            top.append(br)
            i, consumed = 0, []
        else:
            br = stack[i][1]
            m = 1
            while m < len(before) and i + m < len(stack) and stack[i + m][0] == before[m]:
                m += 1
            consumed = stack[i:i + m]
        node = StepNode(cp)
        br.steps.append(node)

        # Goals the step didn't touch (it acted on several but changed only some)
        # keep their branch; the rest are what this step produced.
        others = list(consumed[1:])
        entries: list[tuple[dict, Branch] | dict] = []
        for g in after:
            match = next((e for e in others if e[0] == g), None)
            if match:
                others.remove(match)
                entries.append(match)
            else:
                entries.append(g)
        fresh = [e for e in entries if isinstance(e, dict)]
        if len(fresh) >= 2:
            node.cases = [Branch([g]) for g in fresh]
            owner = iter(node.cases)
            entries = [e if not isinstance(e, dict) else (e, next(owner)) for e in entries]
        else:
            entries = [e if not isinstance(e, dict) else (e, br) for e in entries]
        stack[i:i + len(consumed)] = entries
    return top


class Graph:
    def __init__(self, name: str, mode: str = "split"):
        self.name = name
        self.mode = mode
        self.lines: list[str] = []
        self.n = 0
        self.clusters = 0

    def fresh(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n}"

    # -- nodes ---------------------------------------------------------------

    def state(self, goals: list[dict], prev: list[dict] | None, more: bool = False,
              closed: str = "no goals ✓") -> str:
        """A proof state. Shows only hypotheses that weren't in `prev`.

        `more`: the goals are empty but later steps follow. tactic-roles records
        only the focused goal (bullets, `<;>`), so this means "this goal is
        closed", not "the proof is finished"."""
        node = self.fresh("s")
        if not goals and more:
            self.lines.append(
                f'{node} [label=<<b>goal closed ✓</b><br/><font point-size="9">next goal follows</font>>, '
                f'shape=box, style="rounded,filled,dashed", fillcolor="#eef8ee", color="#3c9a3c", '
                f'fontcolor="#1e5e1e"];')
            return node
        if not goals:
            self.lines.append(
                f'{node} [label=<<b>{closed}</b>>, shape=box, style="rounded,filled", '
                f'fillcolor="#d9f2d9", color="#3c9a3c", fontcolor="#1e5e1e"];')
            return node
        before = {hyp_str(h) for g in (prev or []) for h in g["hypotheses"]}
        rows = []
        for k, g in enumerate(goals):
            new = [hyp_str(h) for h in g["hypotheses"] if hyp_str(h) not in before]
            if k:
                rows.append('<tr><td align="left"><font point-size="9" color="#888888">'
                            '─────── next goal ───────</font></td></tr>')
            old_names = {h["name"] for pg in (prev or []) for h in pg["hypotheses"]}
            for h in new:
                changed = h.split(" : ", 1)[0] in old_names  # e.g. after `rw ... at h`
                for i, line in enumerate(wrap(h)):
                    mark = ("~ " if changed else "+ ") if i == 0 and prev is not None else ""
                    rows.append(f'<tr><td align="left"><font color="#555555">{esc(mark + line)}</font></td></tr>')
            for i, line in enumerate(wrap(g["target"])):
                rows.append(f'<tr><td align="left"><b>{"⊢ " if i == 0 else "  "}{esc(line)}</b></td></tr>')
        tooltip = "\n\n".join(
            "\n".join(hyp_str(h) for h in g["hypotheses"]) + "\n⊢ " + g["target"] for g in goals)
        self.lines.append(
            f'{node} [label=<<table border="0" cellspacing="0" cellpadding="1">{"".join(rows)}</table>>, '
            f'shape=box, style="rounded,filled", fillcolor="white", color="#999999", '
            f'tooltip="{esc(tooltip)}"];')
        return node

    def tactic(self, cp: dict) -> str:
        node = self.fresh("t")
        lines = [l for l in cp["tactic"].strip().splitlines() if not l.strip().startswith("--")]
        shown = [w for l in lines for w in wrap(l, 60)]
        if len(shown) > MAX_TACTIC_LINES:
            shown = shown[:MAX_TACTIC_LINES] + ["…"]
        rows = "".join(f'<tr><td align="left"><font face="Menlo">{esc(l)}</font></td></tr>' for l in shown)
        rules, loc = rewrite_rules(cp["tactic"])
        if len(rules) > 1 or loc:
            where = f" at {loc}" if loc else ""
            rows += (f'<tr><td align="left"><font point-size="9" color="#7a4a00">'
                     f'{len(rules)} rule{"s" if len(rules) != 1 else ""}{esc(where)}:</font></td></tr>')
            rows += "".join(f'<tr><td align="left"><font point-size="10" color="#7a4a00">'
                            f'  {k}. {esc(r)}</font></td></tr>' for k, r in enumerate(rules, 1))
        kind = cp["kind"].split(".")[-1]
        rows += f'<tr><td align="left"><font point-size="9" color="#4a6fa5">#{cp["id"]} · {esc(kind)}</font></td></tr>'
        used = ", ".join(cp.get("usedConstants", [])[:40])
        self.lines.append(
            f'{node} [label=<<table border="0" cellspacing="0" cellpadding="1">{rows}</table>>, '
            f'shape=box, style="filled", fillcolor="#e6efff", color="#4a6fa5", '
            f'tooltip="{esc(cp["tactic"].strip())}&#10;&#10;uses: {esc(used)}"];')
        return node

    def edge(self, a: str, b: str, **attrs: str) -> None:
        extra = "".join(f', {k}="{esc(v)}"' for k, v in attrs.items())
        self.lines.append(f"{a} -> {b} [arrowsize=0.7{extra}];")

    # -- proofs --------------------------------------------------------------

    def proof(self, steps: list[dict], prev_goals: list[dict] | None = None) -> list[str]:
        """Draw a tactic sequence; return the node(s) it starts from."""
        if not steps:
            return []
        if self.mode == "order":
            return [self.chain(steps, prev_goals)]
        branches = case_tree(steps)
        if len(branches) == 1:
            return [self.branch(branches[0], prev_goals, top=True)]
        # Several independent starts (e.g. the alternatives of `induction ... with`).
        return [self.case(b, k, len(branches), prev_goals) for k, b in enumerate(branches)]

    def chain(self, steps: list[dict], prev_goals: list[dict] | None) -> str:
        """Order view: the steps in source order, as one chain."""
        first = cur = self.state(steps[0]["goalsBefore"], prev_goals)
        goals = steps[0]["goalsBefore"]
        for k, cp in enumerate(steps):
            if k and cp["goalsBefore"] != goals:
                # The step works on a goal the previous state doesn't show (after a
                # bullet closed one goal, the next one comes into focus): draw it.
                nxt = self.state(cp["goalsBefore"], steps[0]["goalsBefore"])
                self.edge(cur, nxt, weight="10", style="dashed")
                cur, goals = nxt, cp["goalsBefore"]
            t = self.step(cp, goals)
            self.edge(cur, t, weight="10")
            nxt = self.state(cp["goalsAfter"], goals, more=k + 1 < len(steps))
            self.edge(t, nxt, weight="10")
            cur, goals = nxt, cp["goalsAfter"]
        return first

    def branch(self, br: Branch, prev_goals: list[dict] | None, top: bool = False) -> str:
        """Split view: one goal's steps; a step that splits the goal fans out into cases."""
        first = cur = self.state(br.goals, prev_goals)
        goals = br.goals
        for node in br.steps:
            cp = node.cp
            if cp["goalsBefore"] != goals:
                nxt = self.state(cp["goalsBefore"], goals)
                self.edge(cur, nxt, weight="10", style="dashed")
                cur, goals = nxt, cp["goalsBefore"]
            t = self.step(cp, goals)
            self.edge(cur, t, weight="10")
            if node.cases:
                for k, case in enumerate(node.cases):
                    start = self.case(case, k, len(node.cases), goals)
                    self.edge(t, start, weight="5")
                return first
            nxt = self.state(cp["goalsAfter"], goals,
                             closed="no goals ✓" if top else "case closed ✓")
            self.edge(t, nxt, weight="10")
            cur, goals = nxt, cp["goalsAfter"]
        return first

    def case(self, br: Branch, k: int, n: int, prev_goals) -> str:
        self.clusters += 1
        self.lines.append(
            f'subgraph cluster_{self.clusters} {{ label="case {k + 1} of {n}"; style="rounded,filled"; '
            f'fillcolor="#fbfaf3"; color="#c9b458"; fontsize=10; fontcolor="#7a6a1e";')
        start = self.branch(br, prev_goals)
        self.lines.append("}")
        return start

    def step(self, cp: dict, goals: list[dict]) -> str:
        """A tactic node plus the proofs nested inside it."""
        t = self.tactic(cp)
        for j, aux in enumerate(cp["auxiliary"]):
            self.side(t, aux, f"aux proof {j}", "dashed", goals)
        if cp["substeps"]:
            self.side(t, cp["substeps"], "substeps", "dotted", goals)
        return t

    def side(self, tactic: str, steps: list[dict], label: str, style: str, goals) -> None:
        if not steps:
            return
        self.clusters += 1
        self.lines.append(
            f'subgraph cluster_{self.clusters} {{ label="{esc(label)}"; style="{style},rounded"; '
            f'color="#7a7a7a"; fontsize=10; fontcolor="#555555";')
        starts = self.proof(steps, goals)
        self.lines.append("}")
        for start in starts:
            self.edge(tactic, start, style=style, color="#7a7a7a")

    def dot(self) -> str:
        body = "\n  ".join(self.lines)
        return (f'digraph "{esc(self.name)}" {{\n'
                f'  graph [rankdir=TB, nodesep=0.35, ranksep=0.3, fontname="Helvetica"];\n'
                f'  node [fontname="Helvetica", fontsize=11, margin="0.12,0.06"];\n'
                f'  edge [color="#666666"];\n  {body}\n}}\n')


def unit_title(unit: dict, i: int) -> str:
    kind = unit.get("command", "").split(".")[-1] or "command"
    names = ", ".join(unit.get("declarations", [])) or "(anonymous)"
    return f"{kind} {names}" if names != "(anonymous)" else f"{kind} #{i}"


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proof graphs</title>
<style>
body {{ font-family: -apple-system, Helvetica, sans-serif; margin: 24px; background: #fafafa; color: #222; }}
nav a {{ margin-right: 14px; }}
section {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 12px 18px; margin: 18px 0; }}
h2 {{ font-size: 17px; margin: 4px 0 8px; }}
.msg {{ font-size: 13px; font-family: Menlo, monospace; margin: 2px 0; }}
.error {{ color: #b00020; }} .warning {{ color: #a66300; }} .information {{ color: #555; }}
.svg {{ overflow-x: auto; }}
.toggle {{ margin: 4px 0 10px; }}
.toggle button {{ font: inherit; font-size: 13px; padding: 3px 10px; border: 1px solid #bbb; background: #f4f4f4; cursor: pointer; }}
.toggle button:first-child {{ border-radius: 6px 0 0 6px; }} .toggle button:last-child {{ border-radius: 0 6px 6px 0; border-left: 0; }}
.toggle button.on {{ background: #4a6fa5; color: white; border-color: #4a6fa5; }}
section:not(.split) .view-split, section:not(.order) .view-order {{ display: none; }}
</style></head><body>
<h1>Proof graphs — {source}</h1>
<p>White boxes are proof states (new hypotheses marked +, hover for all of them), blue boxes are tactics,
green means no goals left. Dashed boxes are a step's own proof (<code>have … := by …</code>, <code>calc</code>).</p>
<p>Proofs with several goals: <b>split</b> gives each goal its own "case" block; <b>in order</b> keeps the steps
in source order. <button onclick="all('split')">split all</button> <button onclick="all('order')">in order all</button></p>
<nav>{nav}</nav>
{sections}
<script>
function show(id, mode) {{
  const s = document.getElementById(id);
  s.classList.remove('split', 'order'); s.classList.add(mode);
  s.querySelectorAll('.toggle button').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
}}
function all(mode) {{ document.querySelectorAll('section').forEach(s => show(s.id, mode)); }}
</script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", type=Path, help="output of tactic-roles")
    ap.add_argument("-o", "--out", type=Path, help="HTML file to write (default: next to the JSON)")
    ap.add_argument("--dot", type=Path, metavar="DIR", help="also write one .dot file per proof into DIR")
    ap.add_argument("--png", type=Path, metavar="DIR", help="also write one .png image per proof into DIR")
    ap.add_argument("--cases", choices=["split", "order"], default="split",
                    help="view shown first, and used for --png/--dot (default: split)")
    args = ap.parse_args()

    if not shutil.which("dot"):
        sys.exit("Graphviz's `dot` was not found; install it with `brew install graphviz`.")
    data = json.loads(args.json.read_text(encoding="utf-8"))
    out = args.out or args.json.with_suffix(".html")
    for d in (args.dot, args.png):
        if d:
            d.mkdir(parents=True, exist_ok=True)

    nav, sections = [], []
    for i, unit in enumerate(data["units"]):
        if not unit["checkpoints"]:
            continue
        title = unit_title(unit, i)
        svgs = {}
        for mode in ("split", "order"):
            g = Graph(title, mode)
            g.proof(unit["checkpoints"])
            src = g.dot()
            if mode == args.cases:
                safe = f'{i:02d}_{"".join(c if c.isalnum() or c in "-_" else "_" for c in title)}'
                if args.dot:
                    (args.dot / f"{safe}.dot").write_text(src, encoding="utf-8")
                if args.png:
                    subprocess.run(["dot", "-Tpng", "-Gdpi=110", "-o", str(args.png / f"{safe}.png")],
                                   input=src, text=True, check=True)
            svg = subprocess.run(["dot", "-Tsvg"], input=src, capture_output=True, text=True, check=True).stdout
            svgs[mode] = svg[svg.index("<svg"):]  # drop the XML prolog so it can be inlined
        msgs = "".join(
            f'<div class="msg {esc(m.get("severity", ""))}">{esc(m.get("severity", ""))} '
            f'at line {m.get("pos", ["?"])[0]}: {esc(m.get("text", ""))}</div>'
            for m in unit.get("messages", []))
        nav.append(f'<a href="#u{i}">{esc(title)}</a>')
        toggle = "".join(
            f'<button data-mode="{m}" class="{"on" if m == args.cases else ""}" '
            f'onclick="show(\'u{i}\', \'{m}\')">{label}</button>'
            for m, label in (("split", "split cases"), ("order", "in order")))
        sections.append(
            f'<section id="u{i}" class="{args.cases}"><h2>{esc(title)}</h2>{msgs}'
            f'<div class="toggle">{toggle}</div>'
            f'<div class="svg view-split">{svgs["split"]}</div>'
            f'<div class="svg view-order">{svgs["order"]}</div></section>')

    out.write_text(PAGE.format(source=esc(args.json.name), nav="".join(nav), sections="\n".join(sections)),
                   encoding="utf-8")
    print(f"wrote {out} ({len(sections)} proofs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
