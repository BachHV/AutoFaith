"""Draw the proofs in a tactic-deps JSON with their dependencies.

    python3 FLproof/deps_graph.py proof_deps.json            # writes proof_deps.html
    python3 FLproof/deps_graph.py proof_deps.json --png DIR  # also one .png per proof
    python3 FLproof/deps_graph.py proof_deps.json --notation # also show +, *, <, instances

Same layout as graph.py (proof states, tactics, cases, aux proofs), plus:
  - on each tactic box, what it does with the premises of the state before it:
      uses: hk, hm          (green)   the step's proof term refers to them
      changes: ha           (orange)  removed or replaced (`obtain ... := ha`, `rw ... at h`)
      not computed: h1, h2  (grey)    `omega` / `simp` steps
    Unused premises are not listed.
  - one oval per dependency outside the proof, with a dashed arrow to every step
    that uses it. Colour = where it is declared: this file (orange), Mathlib
    (purple), Lean core (grey). Hover an oval for its file.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import graph
from graph import Graph, esc, wrap, rewrite_rules, unit_title, MAX_TACTIC_LINES

ORIGIN_STYLE = {
    "file": ("#fff1e0", "#d08a2e"),
    "mathlib": ("#f1e9fb", "#8a5cc2"),
    "core": ("#f0f0f0", "#888888"),
    "other": ("#ffffff", "#999999"),
}


def origin(location: str, this_file: str) -> str:
    if location == this_file or not location.endswith(".lean") or "/" not in location:
        return "file" if location == this_file else "other"
    if "packages/mathlib/" in location:
        return "mathlib"
    if "/toolchains/" in location:
        return "core"
    return "other"


def short(location: str) -> str:
    for marker in ("packages/mathlib/", "/src/lean/"):
        if marker in location:
            return location.split(marker, 1)[1]
    return location


class DepsGraph(Graph):
    def __init__(self, name: str, mode: str, this_file: str, notation: bool):
        super().__init__(name, mode)
        self.this_file = this_file
        self.notation = notation
        self.dep_nodes: dict[str, str] = {}

    def dep_node(self, name: str, location: str) -> str:
        if name not in self.dep_nodes:
            node = self.fresh("d")
            fill, line = ORIGIN_STYLE[origin(location, self.this_file)]
            self.dep_nodes[name] = node
            self.lines.append(
                f'{node} [label=<{esc(name)}>, shape=oval, style="filled", fillcolor="{fill}", '
                f'color="{line}", fontsize=10, tooltip="{esc(short(location))}"];')
        return self.dep_nodes[name]

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
        # Premise usage of the state before the step (moved aside by strip_usage).
        marks: dict[str, list[str]] = {}
        for name, u in cp.get("_usage", []):
            if u != "unused" and name not in marks.get(u, []):
                marks.setdefault(u, []).append(name)
        for usage, label, color in (("used", "uses", "#2e7d32"), ("changed", "changes", "#c26a00"),
                                    ("not computed", "not computed", "#888888")):
            if marks.get(usage):
                rows += (f'<tr><td align="left"><font point-size="10" color="{color}">'
                         f'{label}: {esc(", ".join(marks[usage]))}</font></td></tr>')
        kind = cp["kind"].split(".")[-1]
        rows += f'<tr><td align="left"><font point-size="9" color="#4a6fa5">#{cp["id"]} · {esc(kind)}</font></td></tr>'
        self.lines.append(
            f'{node} [label=<<table border="0" cellspacing="0" cellpadding="1">{rows}</table>>, '
            f'shape=box, style="filled", fillcolor="#e6efff", color="#4a6fa5", '
            f'tooltip="{esc(cp.get("path", ""))}"];')
        deps = cp.get("dependency", []) + (cp.get("notationDependency", []) if self.notation else [])
        for name, location in deps:
            self.lines.append(f'{self.dep_node(name, location)} -> {node} [style=dashed, color="#b39ddb", '
                              f'arrowsize=0.6, constraint=false];')
        return node


def strip_usage(cp: dict) -> dict:
    """Move the `usage` marks out of the goals into `_usage`, so goals compare
    equal across steps (graph.case_tree matches steps to goals by equality)."""
    cp = dict(cp)
    usage, goals = [], []
    for g in cp.get("goalsBefore", []):
        hyps = []
        for h in g["hypotheses"]:
            h = dict(h)
            if "usage" in h:
                usage.append((h["name"], h.pop("usage")))
            hyps.append(h)
        goals.append({**g, "hypotheses": hyps})
    cp["goalsBefore"], cp["_usage"] = goals, usage
    cp["substeps"] = [strip_usage(c) for c in cp.get("substeps", [])]
    cp["auxiliary"] = [[strip_usage(c) for c in proof] for proof in cp.get("auxiliary", [])]
    return cp


PAGE_NOTE = """<p>Tactic boxes list the premises the step <span style="color:#2e7d32">uses</span>,
<span style="color:#c26a00">changes</span>, or for which usage is <span style="color:#888">not computed</span>
(omega/simp). Ovals are dependencies outside the proof: <span style="color:#d08a2e">this file</span>,
<span style="color:#8a5cc2">Mathlib</span>, <span style="color:#888">Lean core</span>; hover for the file.</p>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", type=Path, help="output of tactic-deps")
    ap.add_argument("-o", "--out", type=Path, help="HTML file to write (default: next to the JSON)")
    ap.add_argument("--png", type=Path, metavar="DIR", help="also write one .png image per proof into DIR")
    ap.add_argument("--cases", choices=["split", "order"], default="split")
    ap.add_argument("--notation", action="store_true", help="also draw notation/instance dependencies")
    args = ap.parse_args()

    if not shutil.which("dot"):
        sys.exit("Graphviz's `dot` was not found; install it with `brew install graphviz`.")
    import json
    data = json.loads(args.json.read_text(encoding="utf-8"))
    this_file = data.get("file", "")
    out = args.out or args.json.with_suffix(".html")
    if args.png:
        args.png.mkdir(parents=True, exist_ok=True)

    nav, sections = [], []
    for i, unit in enumerate(data["units"]):
        if not unit["checkpoints"]:
            continue
        title = unit_title(unit, i)
        svgs = {}
        for mode in ("split", "order"):
            g = DepsGraph(title, mode, this_file, args.notation)
            g.proof([strip_usage(c) for c in unit["checkpoints"]])
            src = g.dot()
            if mode == args.cases and args.png:
                safe = f'{i:02d}_{"".join(c if c.isalnum() or c in "-_" else "_" for c in title)}'
                subprocess.run(["dot", "-Tpng", "-Gdpi=110", "-o", str(args.png / f"{safe}.png")],
                               input=src, text=True, check=True)
            svg = subprocess.run(["dot", "-Tsvg"], input=src, capture_output=True, text=True, check=True).stdout
            svgs[mode] = svg[svg.index("<svg"):]
        toggle = "".join(
            f'<button data-mode="{m}" class="{"on" if m == args.cases else ""}" '
            f'onclick="show(\'u{i}\', \'{m}\')">{label}</button>'
            for m, label in (("split", "split cases"), ("order", "in order")))
        nav.append(f'<a href="#u{i}">{esc(title)}</a>')
        sections.append(
            f'<section id="u{i}" class="{args.cases}"><h2>{esc(title)}</h2>'
            f'<div class="toggle">{toggle}</div>'
            f'<div class="svg view-split">{svgs["split"]}</div>'
            f'<div class="svg view-order">{svgs["order"]}</div></section>')

    page = graph.PAGE.replace("<nav>{nav}</nav>", PAGE_NOTE + "\n<nav>{nav}</nav>").replace(
        "<title>Proof graphs</title>", "<title>Proof dependencies</title>")
    out.write_text(page.format(source=esc(args.json.name), nav="".join(nav), sections="\n".join(sections)),
                   encoding="utf-8")
    print(f"wrote {out} ({len(sections)} proofs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
