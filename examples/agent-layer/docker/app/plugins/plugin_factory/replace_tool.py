"""Replace an existing ``.py`` tool module under AGENT_PLUGINS_EXTRA_DIR (full ``source``)."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import plugin_authoring

from ._tool_factory_common import digest_reload_response, extra_root_or_error, validate_module_text

__version__ = "1.0.0"
PLUGIN_ID = "replace_tool"


def replace_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    fn, fe = plugin_authoring.sanitize_plugin_filename(str(arguments.get("filename") or ""))
    if fe or not fn:
        return json.dumps({"ok": False, "error": fe or "filename required"}, ensure_ascii=False)
    source = arguments.get("source")
    if source is None or not str(source).strip():
        return json.dumps({"ok": False, "error": "source required (full module text)"}, ensure_ascii=False)
    text = str(source)
    val_err = validate_module_text(text, fn, codegen=False)
    if val_err:
        return json.dumps({"ok": False, "error": val_err}, ensure_ascii=False)
    dest = root / fn
    if not dest.is_file():
        return json.dumps(
            {"ok": False, "error": f"file does not exist: {fn}; use create_tool to add a new file"},
            ensure_ascii=False,
        )
    try:
        dest.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)
    return digest_reload_response(fn, dest)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "replace_tool": replace_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "replace_tool",
            "description": (
                "Replace an entire .py tool module with new full source; compile + AST + registry shape check; reload. "
                "For small edits without rewriting the whole file, prefer update_tool (old_string → new_string)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "source": {"type": "string", "description": "Full replacement module text"},
                },
                "required": ["filename", "source"],
            },
        },
    },
]
