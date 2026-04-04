"""Introspection: list registered tools and fetch one tool's OpenAI schema from the live registry."""

from __future__ import annotations

import json
from typing import Any, Callable

from app.registry import get_registry
from app.tool_name_hints import suggest_tool_names

__version__ = "1.1.0"
TOOL_ID = "tool_help"


def list_available_tools(arguments: dict[str, Any]) -> str:
    """Return every tool name, description, and JSON Schema parameters (as registered)."""
    _ = arguments
    reg = get_registry()
    tools_out: list[dict[str, Any]] = []
    for spec in reg.openai_tools:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        tools_out.append(
            {
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
            }
        )
    return json.dumps(
        {
            "ok": True,
            "count": len(tools_out),
            "tools": tools_out,
            "hint": "Use get_tool_help with a tool name for one schema in full, or call a tool with JSON args per parameters.properties / required.",
        },
        ensure_ascii=False,
    )


def get_tool_help(arguments: dict[str, Any]) -> str:
    """Return full description + parameter schema for a single tool."""
    name = (arguments.get("tool_name") or "").strip()
    if not name:
        return json.dumps({"ok": False, "error": "tool_name is required"})
    reg = get_registry()
    for spec in reg.openai_tools:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        if fn.get("name") != name:
            continue
        return json.dumps(
            {
                "ok": True,
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
                "how_to_use": (
                    "The model calls this tool with a JSON object matching "
                    "`parameters.properties`; required keys are in `parameters.required`."
                ),
            },
            ensure_ascii=False,
        )
    suggestions = suggest_tool_names(reg, name)
    return json.dumps(
        {
            "ok": False,
            "error": f"unknown tool: {name}",
            "hint": (
                "Use exact names from list_available_tools. "
                "There is no tool named openai_function or get_tool_result — "
                "call the real tool (e.g. fishing_index) with tool_calls, or list_available_tools first."
            ),
            "suggestions": suggestions,
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "list_available_tools": list_available_tools,
    "get_tool_help": get_tool_help,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_available_tools",
            "description": (
                "Lists all tools this agent can run: name, short description, and JSON parameter schema. "
                "Use when the user asks what you can do, which tools exist, or how to get started."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tool_help",
            "description": (
                "Returns full help for one tool: description and parameter schema. "
                "If the name is wrong, the response includes suggestions (e.g. openweather_retrieve → openweather_current). "
                "Use when the user asks how to use a specific tool by name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Exact tool name from list_available_tools",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
]
