
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import MISSING, asdict, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from faithful_metric.graph.build_graph import FLNode, FLEdge, NodeCategory, EdgeType
else:
    from .build_graph import FLNode, FLEdge, NodeCategory, EdgeType

JSON_MARKER = "AUTOFAITH_BLUEPRINT_JSON:"


class FLGraphExtractionError(RuntimeError):
    pass

def _run_lean(project_path: Path, lean_file: Path, timeout: int = 180) -> dict[str, Any]:
    process = subprocess.run(
        ["lake", "env", "lean", str(lean_file)],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = process.stdout + "\n" + process.stderr
    if process.returncode != 0:
        raise FLGraphExtractionError("Lean failed while extracting the graph.\n\n" + output)

    payload = None
    for line in output.splitlines():
        if JSON_MARKER in line:
            payload = line.split(JSON_MARKER, 1)[1].strip()
            break
    if payload is None:
        raise FLGraphExtractionError(
            "Lean completed, but no AutoFaith graph JSON was found.\n"
            "Make sure the file runs `#autofaith_graph <root>`.\n\n" + output
        )
    return json.loads(payload)


def extract_raw_graph_from_existing_file(
    project_path: str | Path,
    lean_file: str | Path,
    timeout: int = 300,
) -> dict[str, Any]:
    project_path = Path(project_path).resolve()
    lean_file = Path(lean_file)
    if not lean_file.is_absolute():
        lean_file = project_path / lean_file
    return _run_lean(project_path, lean_file, timeout=timeout)


def extract_raw_graph_from_module(
    project_path: str | Path,
    theorem_module: str,
    root_name: str,
    blueprint_module: str = "FLproof.BlueprintGraph",
    timeout: int = 180,
) -> dict[str, Any]:
    project_path = Path(project_path).resolve()
    source = (
        f"import {theorem_module}\n"
        f"import {blueprint_module}\n\n"
        f"#autofaith_graph {root_name}\n"
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lean",
            prefix="_autofaith_runner_",
            dir=project_path,
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write(source)
            temp_path = Path(handle.name)
        return _run_lean(project_path, temp_path, timeout=timeout)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

def _module_relative_path(module_name: str) -> Path:
    return Path(*module_name.split(".")).with_suffix(".lean")


def _lean_prefix(project_path: Path) -> Path | None:
    process = subprocess.run(
        ["lake", "env", "lean", "--print-prefix"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        return None
    value = process.stdout.strip()
    return Path(value) if value else None


def resolve_lean_source_file(project_path: str | Path, module_name: str) -> Path | None:
    """Resolve Mathlib/core/project module names to their original .lean files."""
    project_path = Path(project_path).resolve()
    relative = _module_relative_path(module_name)
    packages = project_path / ".lake" / "packages"

    candidates: list[Path] = [
        project_path / relative,
        packages / "mathlib" / relative,
        packages / "lean4" / "src" / "lean" / relative,
    ]

    if packages.exists():
        for package in packages.iterdir():
            if package.is_dir():
                candidates.append(package / relative)

    prefix = _lean_prefix(project_path)
    if prefix is not None:
        candidates.extend([
            prefix / "src" / "lean" / relative,
            prefix / "src" / relative,
        ])
        if module_name == "Lake":
            candidates.append(prefix / "src" / "lean" / "lake" / "Lake.lean")
        elif module_name.startswith("Lake."):
            tail = Path(*module_name.split(".")[1:]).with_suffix(".lean")
            candidates.append(prefix / "src" / "lean" / "lake" / tail)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return None


_DECLARATION_KEYWORDS = (
    "theorem", "lemma", "def", "abbrev", "opaque", "axiom",
    "inductive", "structure", "class", "instance",
)

def _declaration_name_regex(full_name: str) -> re.Pattern[str]:
    short_name = re.escape(full_name.rsplit(".", 1)[-1])
    keywords = "|".join(_DECLARATION_KEYWORDS)
    return re.compile(
        rf"""
        ^[ \t]*
        (?:(?:protected|private|noncomputable|unsafe|partial)[ \t]+)*
        (?:{keywords})[ \t]+
        (?:[A-Za-z0-9_.'«»]+[.])*
        {short_name}\b
        """,
        re.MULTILINE | re.VERBOSE,
    )


def _contains_declaration_name(text: str, full_name: str) -> bool:
    return _declaration_name_regex(full_name).search(text) is not None


def _slice_from_lean_range(
    source: str,
    full_name: str,
    start_line: int | None,
    end_line: int | None,
) -> str | None:
    """Use Lean's declaration range first; try both 0- and 1-based line conventions."""
    if start_line is None or end_line is None:
        return None
    lines = source.splitlines(keepends=True)
    for base in (0, 1):
        start = start_line - base
        end = end_line - base
        if start < 0 or start >= len(lines):
            continue
        end = min(len(lines) - 1, max(start, end))
        candidate = "".join(lines[start:end + 1]).strip()
        if _contains_declaration_name(candidate, full_name):
            return candidate
    return None


_TOP_LEVEL_BOUNDARY = re.compile(
    r"""
    ^(?P<indent>[ \t]*)
    (?:(?:protected|private|noncomputable|unsafe|partial)\s+)*
    (?:theorem|lemma|def|abbrev|opaque|axiom|inductive|structure|class|instance|namespace|section|instance|end)\b
    """,
    re.MULTILINE | re.VERBOSE,
)


def _extract_declaration_fallback(
    source: str,
    full_name: str,
    start_line_hint: int | None = None,
) -> str | None:
    regex = _declaration_name_regex(full_name)
    matches = list(regex.finditer(source))
    if not matches:
        return None

    if len(matches) > 1 and start_line_hint is not None:
        def line_number(m: re.Match[str]) -> int:
            return source.count("\n", 0, m.start()) + 1
        match = min(matches, key=lambda m: abs(line_number(m) - start_line_hint))
    else:
        match = matches[0]

    start = match.start()
    line_start = source.rfind("\n", 0, start) + 1
    start_indent = len(source[line_start:start].expandtabs(4))
    end = len(source)

    for boundary in _TOP_LEVEL_BOUNDARY.finditer(source, match.end()):
        boundary_line_start = source.rfind("\n", 0, boundary.start()) + 1
        indent = len(source[boundary_line_start:boundary.start()].expandtabs(4))
        if indent <= start_indent:
            end = boundary.start()
            break

    return source[start:end].strip()


def extract_source_declaration(source: str, raw_node: dict[str, Any]) -> str | None:
    declaration = _slice_from_lean_range(
        source,
        raw_node["name"],
        raw_node.get("sourceStartLine"),
        raw_node.get("sourceEndLine"),
    )
    if declaration is not None:
        return declaration
    return _extract_declaration_fallback(
        source,
        raw_node["name"],
        raw_node.get("sourceStartLine"),
    )

def extract_declaration_body(
    declaration: str | None,
) -> str | None:
    """
    Extract everything after := from a Lean declaration.

    theorem foo : P := by
      ...
        -> by
             ...

    def foo (x : Nat) : Nat :=
      x + 1
        -> x + 1
    """

    if declaration is None:
        return None

    assignment = declaration.find(":=")

    if assignment == -1:
        return None

    body = declaration[
        assignment + 2:
    ].strip()

    return body or None

def extract_source_proof(declaration: str | None) -> str | None:
    """Return the original source proof/value after `:=`; tactic proofs start with `by`."""
    if declaration is None:
        return None
    assignment = declaration.find(":=")
    if assignment == -1:
        return None
    proof = declaration[assignment + 2:].strip()
    return proof or None


def enrich_raw_graph_with_source(
    raw_graph: dict,
    project_path: str | Path,
) -> dict:

    project_path = Path(
        project_path
    ).resolve()

    source_cache: dict[Path, str] = {}

    enriched_nodes = []

    for original in raw_graph["nodes"]:

        node = dict(original)
        source_path = resolve_lean_source_file(
            project_path,
            node["moduleName"],
        )

        node["source_path"] = (
            str(source_path)
            if source_path is not None
            else None
        )
        declaration = None

        if source_path is not None:

            if source_path not in source_cache:

                source_cache[source_path] = (
                    source_path.read_text(
                        encoding="utf-8"
                    )
                )

            declaration = (
                extract_source_declaration(
                    source_cache[source_path],
                    node,
                )
            )

        node["source_declaration"] = (
            declaration
        )

        body = extract_declaration_body(
            declaration
        )
        if node["category"] == "THEOREM":

            node["proof"] = body
            node["definition"] = None

        elif node["category"] == "DEFINITION":

            node["proof"] = None
            node["definition"] = body

        else:
            node["proof"] = None
            node["definition"] = None

        enriched_nodes.append(
            node
        )

    return {
        **raw_graph,
        "nodes": enriched_nodes,
    }


def _field_names(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _required_fields(cls: type) -> set[str]:
    return {
        field.name
        for field in fields(cls)
        if field.default is MISSING and field.default_factory is MISSING
    }


def _make_fl_node(raw: dict[str, Any], node_id: int) -> FLNode:
    available = _field_names(FLNode)
    source_path = raw.get("source_path")
    values: dict[str, Any] = {
        "id": node_id,
        "category": NodeCategory[raw["category"]],
        "statement": raw["statement"],
        "proof": raw.get("proof"),
        "directory": source_path or raw["moduleName"],
        "definition": raw.get("definition"),
        "module_name": raw["moduleName"],
        "source_declaration": raw.get("source_declaration"),
    }
    kwargs = {k: v for k, v in values.items() if k in available}
    missing = _required_fields(FLNode) - kwargs.keys()
    if missing:
        raise FLGraphExtractionError(
            f"Cannot construct FLNode; missing required fields: {sorted(missing)}"
        )
    return FLNode(**kwargs)


def _make_fl_edge(source: FLNode, target: FLNode, kind: str) -> FLEdge:
    available = _field_names(FLEdge)
    values: dict[str, Any] = {
        "source": source,
        "target": target,
        "type": EdgeType[kind],
        "evidence": None,
        "explicit": True,
        "confidence": 1.0,
    }
    kwargs = {k: v for k, v in values.items() if k in available}
    missing = _required_fields(FLEdge) - kwargs.keys()
    if missing:
        raise FLGraphExtractionError(
            f"Cannot construct FLEdge; missing required fields: {sorted(missing)}"
        )
    return FLEdge(**kwargs)


def convert_to_fl_graph(raw_graph: dict[str, Any]) -> tuple[list[FLNode], list[FLEdge]]:
    root_name = raw_graph["root"]
    raw_by_name = {node["name"]: node for node in raw_graph["nodes"]}
    if root_name not in raw_by_name:
        raise FLGraphExtractionError(f"Root {root_name!r} missing from node list")

    ordered_names = [root_name] + sorted(name for name in raw_by_name if name != root_name)
    node_by_name = {
        name: _make_fl_node(raw_by_name[name], node_id)
        for node_id, name in enumerate(ordered_names)
    }

    edges = []
    for raw_edge in raw_graph["edges"]:
        if raw_edge["source"] in node_by_name and raw_edge["target"] in node_by_name:
            edges.append(
                _make_fl_edge(
                    node_by_name[raw_edge["source"]],
                    node_by_name[raw_edge["target"]],
                    raw_edge["kind"],
                )
            )
    return [node_by_name[name] for name in ordered_names], edges


def build_fl_graph_from_existing_file(
    project_path: str | Path,
    lean_file: str | Path,
    mine_source_proofs: bool = True,
    timeout: int = 300,
) -> tuple[list[FLNode], list[FLEdge]]:
    raw = extract_raw_graph_from_existing_file(project_path, lean_file, timeout=timeout)
    if mine_source_proofs:
        raw = enrich_raw_graph_with_source(raw, project_path)
    return convert_to_fl_graph(raw)


def build_fl_graph_from_module(
    project_path: str | Path,
    theorem_module: str,
    root_name: str,
    blueprint_module: str = "FLproof.BlueprintGraph",
    mine_source_proofs: bool = True,
    timeout: int = 300,
) -> tuple[list[FLNode], list[FLEdge]]:
    raw = extract_raw_graph_from_module(
        project_path,
        theorem_module,
        root_name,
        blueprint_module=blueprint_module,
        timeout=timeout,
    )
    if mine_source_proofs:
        raw = enrich_raw_graph_with_source(raw, project_path)
    return convert_to_fl_graph(raw)


def build_raw_json_from_existing_file(
    project_path: str | Path,
    lean_file: str | Path,
    output_path: str | Path,
    mine_source_proofs: bool = True,
    timeout: int = 180,
) -> dict[str, Any]:
    raw = extract_raw_graph_from_existing_file(project_path, lean_file, timeout=timeout)
    if mine_source_proofs:
        raw = enrich_raw_graph_with_source(raw, project_path)
    Path(output_path).write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return raw


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _graph_to_jsonable(graph: tuple[list[FLNode], list[FLEdge]]) -> dict[str, list[dict[str, Any]]]:
    nodes, edges = graph
    return {
        "nodes": [asdict(node) for node in nodes],
        "edges": [asdict(edge) for edge in edges],
    }


if __name__ == "__main__":
    lean_project = Path("/Users/vietbachhoang/AutoFaith/faithful_metric/FLproof")
    theorem_module = "FLproof.proof"
    root_name = "mathlibExample"
    graph = build_fl_graph_from_module(lean_project, theorem_module, root_name)

    output_path = lean_project.parent / "fl_graph.json"
    output_path.write_text(
        json.dumps(_graph_to_jsonable(graph), indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    print(f"Wrote graph JSON to {output_path}")
    print(graph)