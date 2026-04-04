"""Apply a substring patch to an existing ``.py`` under AGENT_PLUGINS_EXTRA_DIR (then validate + reload)."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import plugin_authoring

from ._tool_factory_common import digest_reload_response, extra_root_or_error, validate_module_text

__version__ = "1.1.0"
PLUGIN_ID = "update_tool"


def update_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    fn, fe = plugin_authoring.sanitize_plugin_filename(str(arguments.get("filename") or ""))
    if fe or not fn:
        return json.dumps({"ok": False, "error": fe or "filename required"}, ensure_ascii=False)
    old = arguments.get("old_string")
    if old is None:
        return json.dumps({"ok": False, "error": "old_string is required"}, ensure_ascii=False)
    new = arguments.get("new_string")
    if new is None:
        new = ""
    old_s = str(old)
    new_s = str(new)

    dest = root / fn
    if not dest.is_file():
        return json.dumps(
            {"ok": False, "error": f"file does not exist: {fn}; use create_tool to add a new file"},
            ensure_ascii=False,
        )
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    count = text.count(old_s)
    if count == 0:
        return json.dumps({"ok": False, "error": "old_string not found", "filename": fn}, ensure_ascii=False)
    try:
        replace_all = bool(arguments.get("replace_all", False))
    except Exception:
        replace_all = False
    if not replace_all and count != 1:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"old_string matches {count} times; set replace_all true to replace all, "
                    "or make old_string unique (include more surrounding context)"
                ),
                "matches": count,
            },
            ensure_ascii=False,
        )
    if replace_all:
        updated = text.replace(old_s, new_s)
        replaced = count
    else:
        updated = text.replace(old_s, new_s, 1)
        replaced = 1

    val_err = validate_module_text(updated, fn, codegen=False)
    if val_err:
        return json.dumps(
            {
                "ok": False,
                "error": val_err,
                "hint": "File not written. Fix old_string/new_string or use read_tool then replace_tool with full source.",
            },
            ensure_ascii=False,
        )

    try:
        dest.write_text(updated, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

    body = json.loads(digest_reload_response(fn, dest))
    body["replacements"] = replaced
    return json.dumps(body, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "update_tool": update_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_tool",
            "description": (
                "Patch an existing .py tool module: replace old_string with new_string (like workspace_replace_text). "
                "Unless replace_all is true, old_string must match exactly once. "
                "After the edit: compile + AST + registry check + reload. "
                "Typical flow: read_tool → update_tool. For full file rewrite use replace_tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Basename under AGENT_PLUGINS_EXTRA_DIR"},
                    "old_string": {"type": "string", "description": "Exact substring to replace (use enough context to be unique)"},
                    "new_string": {"type": "string", "description": "Replacement text (may be empty to delete old_string)"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "If true, replace every occurrence of old_string",
                    },
                },
                "required": ["filename", "old_string"],
            },
        },
    },
]
