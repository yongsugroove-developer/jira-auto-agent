from __future__ import annotations

import ast
from pathlib import Path



def test_main_uses_single_test_changes_implementation() -> None:
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    module = ast.parse(main_path.read_text(encoding="utf-8"))

    test_change_defs = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_test_changes", "_test_changes_plain"}
    ]

    assert len(test_change_defs) == 1



def test_main_defines_setup_guide_sections_only_once() -> None:
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    module = ast.parse(main_path.read_text(encoding="utf-8"))

    setup_guide_defs = [
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_setup_guide_sections"
    ]

    assert len(setup_guide_defs) == 1



def test_main_defines_batch_status_helpers_only_once() -> None:
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    module = ast.parse(main_path.read_text(encoding="utf-8"))

    helper_names = {
        "_batch_status_message",
        "_batch_suggested_active_run_id",
        "_batch_aggregate_status",
    }
    counts = {
        name: len([
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name
        ])
        for name in helper_names
    }

    assert counts == {
        "_batch_status_message": 1,
        "_batch_suggested_active_run_id": 1,
        "_batch_aggregate_status": 1,
    }
