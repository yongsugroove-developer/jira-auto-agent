from __future__ import annotations

import inspect

from app.routes.workflow_routes import register_workflow_routes



def test_register_workflow_routes_does_not_require_unused_scm_store_key() -> None:
    signature = inspect.signature(register_workflow_routes)

    assert "scm_store_key" not in signature.parameters
