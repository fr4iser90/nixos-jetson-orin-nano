"""Read full source of one ``.py`` tool module under AGENT_PLUGINS_EXTRA_DIR."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import config
from app import plugin_authoring

from ._tool_factory_common import extra_root_or_error

__version__ = "1.0.0"
PLUGIN_ID = "read_tool"


def read_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    fn, fe = plugin_authoring.sanitize_plugin_filename(str(arguments.get("filename") or ""))
    if fe or not fn:
        return json.dumps({"ok": False, "error": fe or "filename required"}, ensure_ascii=False)
    dest = root / fn
    if not dest.is_file():
        return json.dumps({"ok": False, "error": f"not found: {fn}"}, ensure_ascii=False)
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return json.dumps(
            {
                "ok": False,
                "error": f"file larger than AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES})",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "filename": fn, "source": text, "byte_length": len(text.encode("utf-8"))},
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "read_tool": read_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_tool",
            "description": (
                "Return full UTF-8 source of one .py file under AGENT_PLUGINS_EXTRA_DIR "
                "(same size limit as create_tool)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Basename e.g. my_tool.py"},
                },
                "required": ["filename"],
            },
        },
    },
]
