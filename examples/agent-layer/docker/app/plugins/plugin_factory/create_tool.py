"""Create extra plugins (full ``source`` or Ollama codegen). See sibling modules for list/read/update/rename."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import config
from app import plugin_authoring

from app.plugins.plugin_factory._tool_factory_common import (
    coerce_test_args,
    digest_reload_response,
    extra_root_or_error,
    ollama_generate_module,
    retry_hint_from_response,
    validate_module_text,
)

__version__ = "1.3.0"
PLUGIN_ID = "create_tool"


def create_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    extra_root = root

    source_raw = arguments.get("source")
    source_str = str(source_raw).strip() if source_raw is not None else ""
    codegen = not source_str
    codegen_model: str | None = None

    if codegen:
        hint = str(arguments.get("tool_name") or arguments.get("name") or "").strip()
        if not hint:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "Either pass source+filename, or omit source and set tool_name (or name) "
                        "so the server can generate code via Ollama (AGENT_CREATE_TOOL_CODEGEN_MODEL)."
                    ),
                },
                ensure_ascii=False,
            )
        snake, terr = plugin_authoring.slugify_openai_tool_name(hint)
        if terr:
            return json.dumps({"ok": False, "error": terr}, ensure_ascii=False)
        fn, fe = plugin_authoring.sanitize_plugin_filename(f"{snake}.py")
        if fe or not fn:
            return json.dumps({"ok": False, "error": fe or "invalid filename"}, ensure_ascii=False)
        extra_desc = str(arguments.get("description") or "").strip()
        codegen_model = config.CREATE_TOOL_CODEGEN_MODEL
        overwrite = bool(arguments.get("overwrite", False))
        dest = extra_root / fn
        if dest.exists() and not overwrite:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"file already exists: {fn}; pass overwrite:true to replace",
                },
                ensure_ascii=False,
            )

        max_at = config.CREATE_TOOL_CODEGEN_MAX_ATTEMPTS
        fix_hint: str | None = None
        last_body: dict[str, Any] | None = None
        test_args = coerce_test_args(arguments.get("test_arguments"))

        for attempt in range(max_at):
            text, gen_err = ollama_generate_module(
                openai_tool_name=snake,
                display_hint=hint,
                extra_description=extra_desc,
                repair_context=fix_hint,
            )
            if gen_err:
                return json.dumps(
                    {
                        "ok": False,
                        "error": gen_err,
                        "codegen": True,
                        "model": codegen_model,
                        "codegen_attempts": attempt + 1,
                        "codegen_max_attempts": max_at,
                    },
                    ensure_ascii=False,
                )

            val_err = validate_module_text(text, fn, codegen=True)
            if val_err:
                fix_hint = f"Validation failed: {val_err}"
                if attempt >= max_at - 1:
                    return json.dumps(
                        {
                            "ok": False,
                            "error": val_err,
                            "codegen": True,
                            "model": codegen_model,
                            "codegen_attempts": attempt + 1,
                            "codegen_max_attempts": max_at,
                        },
                        ensure_ascii=False,
                    )
                continue

            try:
                dest.write_text(text, encoding="utf-8", newline="\n")
            except OSError as e:
                return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

            body_str = digest_reload_response(
                fn,
                dest,
                codegen=True,
                codegen_model=codegen_model,
                test_tool_name=snake,
                test_arguments=test_args,
            )
            out = json.loads(body_str)
            out["codegen_attempts"] = attempt + 1
            out["codegen_max_attempts"] = max_at
            retry, rhint = retry_hint_from_response(out)
            if not retry:
                return json.dumps(out, ensure_ascii=False)
            fix_hint = (
                rhint
                + "\n\nUse defaults for missing arguments (arguments.get with fallbacks); "
                "never compare None to numbers."
            )
            last_body = out

        if last_body is not None:
            last_body["codegen_attempts_exhausted"] = True
            return json.dumps(last_body, ensure_ascii=False)
        return json.dumps(
            {
                "ok": False,
                "error": "codegen probe retries exhausted",
                "codegen": True,
                "model": codegen_model,
                "codegen_max_attempts": max_at,
            },
            ensure_ascii=False,
        )

    fn, fn_err = plugin_authoring.sanitize_plugin_filename(str(arguments.get("filename") or ""))
    if fn_err:
        return json.dumps({"ok": False, "error": fn_err}, ensure_ascii=False)
    text = source_str

    val_err = validate_module_text(text, fn, codegen=False)
    if val_err:
        return json.dumps(
            {"ok": False, "error": val_err, "codegen": codegen},
            ensure_ascii=False,
        )

    overwrite = bool(arguments.get("overwrite", False))
    dest = extra_root / fn
    if dest.exists() and not overwrite:
        return json.dumps(
            {
                "ok": False,
                "error": f"file already exists: {fn}; pass overwrite:true to replace",
            },
            ensure_ascii=False,
        )

    try:
        dest.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

    return digest_reload_response(
        fn,
        dest,
        codegen=codegen,
        codegen_model=codegen_model,
        test_tool_name=None,
        test_arguments=coerce_test_args(arguments.get("test_arguments")),
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "create_tool": create_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_tool",
            "description": (
                "Create a new tool module (.py with TOOLS + HANDLERS) under AGENT_PLUGINS_EXTRA_DIR. "
                "(1) filename + source, or (2) omit source: tool_name + optional description → Ollama codegen. "
                "Codegen retries: AGENT_CREATE_TOOL_CODEGEN_MAX_ATTEMPTS (default 1). "
                "Related: list_tools, read_tool, update_tool (patch), replace_tool (full file), rename_tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Codegen: short idea (e.g. fishingIndex) → snake_case file + tool name.",
                    },
                    "name": {"type": "string", "description": "Alias for tool_name (codegen)."},
                    "description": {
                        "type": "string",
                        "description": "Codegen: domain hints (e.g. Beißindex 0–10, OpenWeather via httpx).",
                    },
                    "filename": {"type": "string", "description": "With source: basename e.g. my_plugin.py"},
                    "source": {
                        "type": "string",
                        "description": "Full module UTF-8 text; omit to trigger codegen.",
                    },
                    "overwrite": {"type": "boolean"},
                    "test_arguments": {
                        "type": "object",
                        "description": "Optional probe args after codegen reload.",
                    },
                },
            },
        },
    },
]
