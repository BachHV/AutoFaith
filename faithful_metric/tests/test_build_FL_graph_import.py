import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from faithful_metric.graph.build_FL_graph import _make_fl_node


def test_make_fl_node_handles_raw_lean_schema():
    raw = {
        "category": "THEOREM",
        "name": "mathlibExample",
        "statement": "∀ (x : ℝ), √(x ^ 2) = |x|",
        "proof": "by exact Real.sqrt_sq_eq_abs x",
        "moduleName": "FLproof.proof",
        "source_declaration": "theorem mathlibExample ...",
    }

    node = _make_fl_node(raw, 0)

    assert node.definition is None
    assert node.module_name == "FLproof.proof"
    assert node.directory == "FLproof.proof"


def test_build_FL_graph_imports_when_run_as_script():
    script_path = Path(__file__).resolve().parents[1] / "graph" / "build_FL_graph.py"
    graph_dir = str(script_path.parent)

    sys.path.insert(0, graph_dir)
    try:
        spec = importlib.util.spec_from_file_location("build_FL_graph_direct", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        assert hasattr(module, "FLNode")
        assert hasattr(module, "FLEdge")
        assert hasattr(module, "extract_raw_graph_from_module")
    finally:
        if graph_dir in sys.path:
            sys.path.remove(graph_dir)
