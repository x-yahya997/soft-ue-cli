"""Tests for cli/soft_ue_cli/mcp_server.py — MCP server tool/prompt registration."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

# Skip all tests if mcp is not installed
mcp = pytest.importorskip("mcp")

from soft_ue_cli.mcp_server import create_server


def test_create_server_returns_fastmcp():
    from mcp.server.fastmcp import FastMCP
    server = create_server()
    assert isinstance(server, FastMCP)


def test_server_has_tools():
    # NOTE: _tool_manager/_tools are private FastMCP internals.
    # No public enumeration API exists as of mcp 1.26. Update if one is added.
    server = create_server()
    assert server._tool_manager is not None
    assert len(server._tool_manager._tools) >= 60


def test_server_has_prompts():
    server = create_server()
    assert server._prompt_manager is not None
    assert len(server._prompt_manager._prompts) > 0


@patch("soft_ue_cli.client.call_tool")
def test_tool_call_forwards_to_bridge(mock_call_tool):
    mock_call_tool.return_value = {"actors": []}
    server = create_server()

    tool_fn = None
    for tool in server._tool_manager._tools.values():
        if tool.name == "query-level":
            tool_fn = tool.fn
            break

    assert tool_fn is not None, "query-level tool not registered"
    result = tool_fn(limit=10)
    mock_call_tool.assert_called_once()
    call_args = mock_call_tool.call_args
    assert call_args[0][0] == "query-level"
    assert "limit" in call_args[0][1]


@patch("soft_ue_cli.client.call_tool")
def test_tool_call_returns_json_string(mock_call_tool):
    mock_call_tool.return_value = {"status": "ok"}
    server = create_server()

    tool_fn = None
    for tool in server._tool_manager._tools.values():
        if tool.name == "status":
            tool_fn = tool.fn
            break

    assert tool_fn is not None
    result = tool_fn()
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed == {"status": "ok"}


@patch("soft_ue_cli.client.call_tool")
def test_tool_call_handles_system_exit(mock_call_tool):
    mock_call_tool.side_effect = SystemExit(1)
    server = create_server()

    tool_fn = None
    for tool in server._tool_manager._tools.values():
        if tool.name == "status":
            tool_fn = tool.fn
            break

    assert tool_fn is not None
    result = tool_fn()
    assert "error" in result.lower()


def test_prompt_list_has_blueprint_to_cpp():
    server = create_server()
    prompts = server._prompt_manager._prompts
    prompt_names = {p for p in prompts}
    assert "blueprint-to-cpp" in prompt_names


def test_prompt_fn_returns_content():
    server = create_server()
    prompt = server._prompt_manager._prompts.get("blueprint-to-cpp")
    assert prompt is not None
    result = prompt.fn()
    assert isinstance(result, str)
    assert "Blueprint to C++" in result
