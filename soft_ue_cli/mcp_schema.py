"""Argparse introspection → MCP tool schema generation."""

from __future__ import annotations

import argparse
from typing import Any

EXCLUDED_COMMANDS: frozenset[str] = frozenset({
    "skills",
    "mcp-serve",
})

# Per-tool schema overrides. Merged into auto-generated schemas after extraction.
# Use to add pattern constraints, refine descriptions, or mark extra required fields.
TOOL_OVERRIDES: dict[str, dict[str, Any]] = {
    "spawn-actor": {
        "properties": {
            "location": {"description": "Comma-separated X,Y,Z (e.g. 100,200,50)"},
            "rotation": {"description": "Comma-separated Pitch,Yaw,Roll (e.g. 0,90,0)"},
        },
    },
}


def _argparse_type_to_json(action: argparse.Action) -> dict[str, Any]:
    """Convert a single argparse action to a JSON Schema property."""
    prop: dict[str, Any] = {}

    # Type mapping
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        prop["type"] = "boolean"
    elif action.type is int:
        prop["type"] = "integer"
    elif action.type is float:
        prop["type"] = "number"
    else:
        prop["type"] = "string"

    # Choices → enum
    if action.choices is not None:
        prop["enum"] = list(action.choices)

    # Description from help
    if action.help and action.help != argparse.SUPPRESS:
        prop["description"] = action.help

    # Default
    if action.default is not None and action.default != argparse.SUPPRESS:
        prop["default"] = action.default

    return prop


def _extract_one(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Extract a JSON Schema from a single subcommand parser."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for action in parser._actions:
        # Skip help action and subparsers
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue

        # Determine the property name (dest)
        name = action.dest

        # Skip internal argparse fields
        if name in ("command", "func"):
            continue

        prop = _argparse_type_to_json(action)
        properties[name] = prop

        # Positional args are required (option_strings is empty)
        if not action.option_strings and action.required is not False:
            required.append(name)
        # Explicitly required optional args
        elif action.required:
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


def extract_tools() -> list[dict[str, Any]]:
    """Extract MCP tool definitions from the CLI's argparse parser.

    Returns a list of dicts with keys: name, description, parameters.
    """
    from .__main__ import build_parser

    parser = build_parser()

    tools: list[dict[str, Any]] = []

    # Get the subparsers action
    subparsers_action = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
            break

    if subparsers_action is None:
        return tools

    # Get per-choice help strings for better description fallback
    choice_help: dict[str, str] = {}
    for choice_action in subparsers_action._choices_actions:
        choice_help[choice_action.dest] = choice_action.help or ""

    for cmd_name, sub_parser in subparsers_action.choices.items():
        if cmd_name in EXCLUDED_COMMANDS:
            continue

        params = _extract_one(sub_parser)

        # Apply per-tool overrides
        if cmd_name in TOOL_OVERRIDES:
            override = TOOL_OVERRIDES[cmd_name]
            for prop_name, prop_override in override.get("properties", {}).items():
                if prop_name in params["properties"]:
                    params["properties"][prop_name].update(prop_override)

        tools.append({
            "name": cmd_name,
            "description": sub_parser.description or choice_help.get(cmd_name, sub_parser.prog),
            "parameters": params,
        })

    return tools
