from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, render_template


def register_page_routes(
    app: Flask,
    *,
    setup_guide_payload: dict[str, Any],
    agentation_frontend_config: Callable[[], dict[str, Any]],
    load_codex_cli_defaults: Callable[[], dict[str, Any]],
    load_claude_cli_defaults: Callable[[], dict[str, Any]],
    valid_reasoning_efforts: tuple[str, ...],
    valid_claude_permission_modes: tuple[str, ...],
    default_agent_provider: str,
    agent_provider_options_payload: Callable[[], list[dict[str, Any]]],
) -> None:
    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            agentation_frontend=agentation_frontend_config(),
            codex_defaults=load_codex_cli_defaults(),
            claude_defaults=load_claude_cli_defaults(),
            valid_reasoning_efforts=valid_reasoning_efforts,
            valid_claude_permission_modes=valid_claude_permission_modes,
            agent_provider_default=default_agent_provider,
            agent_provider_options=agent_provider_options_payload(),
        )

    @app.get("/api/setup-guide")
    def setup_guide() -> Any:
        return jsonify(setup_guide_payload)
