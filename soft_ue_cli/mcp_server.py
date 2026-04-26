"""MCP server mode for soft-ue-cli.

Exposes CLI commands as MCP tools and skills as MCP prompts
over stdio transport using FastMCP.

The ``mcp`` package is imported at call time so this module
can be imported without mcp installed (for testing/introspection).
"""

from __future__ import annotations

import inspect
import json
import sys
from typing import Any, Optional

import argparse as _argparse

from . import client as _client
from . import streak as _streak
from .errors import BridgeError, ErrorKind, bug_nudge_payload
from .mcp_schema import CLIENT_SIDE_COMMANDS, extract_tools
from .skills import get_skill, list_skills

# CLI command names that differ from their bridge tool names.
_BRIDGE_TOOL_NAME_MAP: dict[str, str] = {
    "class-hierarchy": "get-class-hierarchy",
    "project-info": "get-project-info",
}

_JSON_TYPE_TO_PY: dict[str, type] = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": float,
}


def _build_signature(params: dict | None) -> inspect.Signature:
    """Build a typed inspect.Signature from a tool's JSON Schema parameters dict.

    FastMCP introspects __signature__ to generate the MCP tool's JSON schema,
    so each parameter must be a proper named, typed, keyword-only Parameter.
    """
    if not params:
        return inspect.Signature([])
    properties = params.get("properties", {})
    required_params = set(params.get("required", []))
    sig_params: list[inspect.Parameter] = []
    for param_name, prop in properties.items():
        py_type = _JSON_TYPE_TO_PY.get(prop.get("type", "string"), str)
        if param_name in required_params:
            annotation: Any = py_type
            default = inspect.Parameter.empty
        else:
            annotation = Optional[py_type]
            default = prop.get("default", None)
        sig_params.append(
            inspect.Parameter(
                param_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
    return inspect.Signature(sig_params)


def _make_tool_fn(tool_name: str, params: dict | None = None):
    """Create a bridge tool handler that forwards kwargs to call_tool()."""
    bridge_name = _BRIDGE_TOOL_NAME_MAP.get(tool_name, tool_name)

    def tool_fn(**kwargs: Any) -> str:
        # Filter out None and False (unset optional / store_true args)
        arguments = {k: v for k, v in kwargs.items() if v is not None and v is not False}

        try:
            result = _client.call_tool(bridge_name, arguments)
        except BridgeError as exc:
            error_response = {"error": f"Tool '{tool_name}' failed: {exc.message}"}
            if exc.kind == ErrorKind.UNEXPECTED:
                error_response["bug_report_hint"] = bug_nudge_payload(
                    exc.tool_name, exc.message,
                )
            return json.dumps(error_response, indent=2, ensure_ascii=False)

        # Record streak (best-effort)
        try:
            _streak.record_success(tool_name)
            if _streak.should_nudge_testimonial():
                result["testimonial_nudge"] = {
                    "message": (
                        "You've been using soft-ue-cli successfully for 3+ days! "
                        "If it's been helpful, consider sharing a testimonial."
                    ),
                    "suggested_command": "submit-testimonial",
                    "suggested_args": {
                        "message": "Share what you liked about soft-ue-cli",
                        "agent-name": "your agent name",
                    },
                }
                _streak.mark_nudged()
        except Exception:
            pass

        return json.dumps(result, indent=2, ensure_ascii=False)

    tool_fn.__name__ = tool_name.replace("-", "_")
    tool_fn.__qualname__ = tool_fn.__name__
    tool_fn.__signature__ = _build_signature(params)

    return tool_fn


def _make_client_tool_fn(tool_name: str, cmd_fn, params: dict | None = None):
    """Create a client-side tool handler that runs the existing cmd_* function.

    Captures stdout so the output reaches the MCP client instead of the terminal.
    SystemExit (from error paths in cmd_* handlers) is caught and reported cleanly.
    """

    def tool_fn(**kwargs: Any) -> str:
        namespace = _argparse.Namespace(**kwargs)
        buffer = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buffer
        try:
            cmd_fn(namespace)
        except SystemExit as exc:
            sys.stdout = old_stdout
            output = buffer.getvalue().strip()
            if output:
                return output
            return json.dumps(
                {"error": f"Command '{tool_name}' exited with code {exc.code}"},
                indent=2,
            )
        finally:
            sys.stdout = old_stdout

        output = buffer.getvalue().strip()
        return output or json.dumps({"status": "ok"}, indent=2)

    tool_fn.__name__ = tool_name.replace("-", "_")
    tool_fn.__qualname__ = tool_fn.__name__
    tool_fn.__signature__ = _build_signature(params)

    return tool_fn


def create_server():
    """Create and configure the MCP server with all tools and prompts."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.prompts import Prompt

    mcp = FastMCP("soft-ue-cli")

    # Register tools from argparse introspection
    for tool_def in extract_tools():
        name = tool_def["name"]
        description = tool_def["description"]
        params = tool_def["parameters"]

        if name in CLIENT_SIDE_COMMANDS:
            fn = _make_client_tool_fn(name, tool_def["func"], params)
        else:
            fn = _make_tool_fn(name, params)
        fn.__doc__ = description

        mcp.add_tool(fn, name=name, description=description)

    # Register skills as prompts
    for skill in list_skills():
        skill_name = skill["name"]
        skill_desc = skill["description"]

        def make_prompt_fn(sn: str, sd: str):
            def prompt_fn() -> str:
                content = get_skill(sn)
                return content or f"Skill '{sn}' not found"
            prompt_fn.__name__ = sn.replace("-", "_")
            prompt_fn.__qualname__ = prompt_fn.__name__
            prompt_fn.__doc__ = sd
            return prompt_fn

        prompt = Prompt.from_function(
            make_prompt_fn(skill_name, skill_desc),
            name=skill_name,
            description=skill_desc,
        )
        mcp.add_prompt(prompt)

    return mcp


def run_server() -> None:
    """Run the MCP server over stdio transport."""
    server = create_server()
    server.run(transport="stdio")
