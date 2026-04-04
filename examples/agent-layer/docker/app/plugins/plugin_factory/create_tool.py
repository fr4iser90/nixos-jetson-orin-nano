"""Optional: write a new ``*.py`` plugin into AGENT_PLUGINS_EXTRA_DIR and reload the registry."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

import httpx

from app import config
from app import plugin_authoring
from app.registry import get_registry, reload_registry

logger = logging.getLogger(__name__)

__version__ = "1.1.0"
PLUGIN_ID = "create_tool"


def _coerce_test_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            o = json.loads(s)
            return dict(o) if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _extract_python_from_llm(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if "```" not in t:
        return t
    parts = t.split("```")
    for i in range(1, len(parts), 2):
        block = parts[i].strip()
        if block.lower().startswith("python"):
            block = block[6:].lstrip()
        if "HANDLERS" in block and "TOOLS" in block:
            return block.strip()
    for i in range(1, len(parts), 2):
        block = parts[i].strip()
        if block.lower().startswith("python"):
            block = block[6:].lstrip()
        if block:
            return block.strip()
    return t


def _ollama_generate_module(
    *,
    openai_tool_name: str,
    display_hint: str,
    extra_description: str,
) -> tuple[str | None, str | None]:
    system = (
        "You output ONE complete Python 3.11 module only. No markdown fences. No prose before or after.\n\n"
        "The module MUST:\n"
        "- start with: from __future__ import annotations\n"
        "- import json\n"
        "- from typing import Any, Callable\n"
        '- set __version__ = "0.1.0"\n'
        f'- set PLUGIN_ID = "{openai_tool_name}"\n'
        f"- define def {openai_tool_name}(arguments: dict[str, Any]) -> str that returns json.dumps(...) "
        "with UTF-8-safe strings\n"
        f'- HANDLERS = {{"{openai_tool_name}": {openai_tool_name}}}\n'
        "- TOOLS = [ one OpenAI-style dict: type function, function.name EXACTLY "
        f'"{openai_tool_name}", useful description, JSON Schema parameters ]\n\n'
        "Rules:\n"
        f"- Exactly one tool and one handler key; names must match \"{openai_tool_name}\".\n"
        "- No network, no reading/writing files, no subprocess, no os.system, "
        "no eval/exec/__import__ calls, no httpx/requests/urllib/socket/ssl.\n"
        "- If the idea implies external data (e.g. weather), use deterministic heuristics from "
        "arguments only and say so in the tool description.\n"
    )
    user = (
        f"Implement a plugin for this short name / idea: {display_hint}\n"
        f"OpenAI function name (required, already chosen): {openai_tool_name}\n"
        f"Extra instructions: {extra_description or '(none)'}\n"
    )
    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": config.CREATE_TOOL_CODEGEN_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": 0.2,
    }
    try:
        with httpx.Client(timeout=float(config.CREATE_TOOL_CODEGEN_TIMEOUT)) as client:
            resp = client.post(url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return None, f"codegen HTTP {e.response.status_code}: {e.response.text[:2000]}"
    except Exception as e:
        return None, f"codegen request failed: {e}"

    choice0 = (data.get("choices") or [{}])[0]
    msg = choice0.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "codegen: empty model response"
    raw = _extract_python_from_llm(content)
    if not re.search(r"\bHANDLERS\b", raw) or not re.search(r"\bTOOLS\b", raw):
        return None, "codegen: response does not look like a plugin module"
    return raw, None


def create_tool(arguments: dict[str, Any]) -> str:
    if not config.CREATE_TOOL_ENABLED:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "create_tool is disabled. Set AGENT_CREATE_TOOL_ENABLED=true "
                    "and configure AGENT_PLUGINS_EXTRA_DIR with a writable host-mounted directory."
                ),
            },
            ensure_ascii=False,
        )
    extra_raw = (config.PLUGINS_EXTRA_DIR or "").strip()
    if not extra_raw:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "AGENT_PLUGINS_EXTRA_DIR is not set. Mount a directory (e.g. ./extra_plugins:/data/plugins:rw) "
                    "and set AGENT_PLUGINS_EXTRA_DIR=/data/plugins in docker/.env."
                ),
            },
            ensure_ascii=False,
        )
    extra_root = Path(extra_root_str := extra_raw)
    if not extra_root.is_dir():
        return json.dumps(
            {
                "ok": False,
                "error": f"AGENT_PLUGINS_EXTRA_DIR is not a directory: {extra_root_str}",
            },
            ensure_ascii=False,
        )

    source_raw = arguments.get("source")
    source_str = str(source_raw).strip() if source_raw is not None else ""
    codegen = not source_str
    test_tool_name: str | None = None
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
        text, gen_err = _ollama_generate_module(
            openai_tool_name=snake,
            display_hint=hint,
            extra_description=extra_desc,
        )
        codegen_model = config.CREATE_TOOL_CODEGEN_MODEL
        if gen_err:
            return json.dumps(
                {"ok": False, "error": gen_err, "codegen": True, "model": codegen_model},
                ensure_ascii=False,
            )
        test_tool_name = snake
    else:
        fn, fn_err = plugin_authoring.sanitize_plugin_filename(
            str(arguments.get("filename") or "")
        )
        if fn_err:
            return json.dumps({"ok": False, "error": fn_err}, ensure_ascii=False)
        text = source_str

    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"source exceeds AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES}); "
                    "split into smaller plugins or raise the limit."
                ),
            },
            ensure_ascii=False,
        )

    try:
        compile(text, fn, "exec")
    except SyntaxError as e:
        return json.dumps(
            {
                "ok": False,
                "error": f"compile failed: {e}",
                "codegen": codegen,
            },
            ensure_ascii=False,
        )

    ast_err = plugin_authoring.validate_plugin_source(text)
    if ast_err:
        return json.dumps(
            {"ok": False, "error": ast_err, "codegen": codegen},
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

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    allow = config.plugins_allowed_sha256()

    if allow is not None:
        if digest not in allow:
            return json.dumps(
                {
                    "ok": True,
                    "written": fn,
                    "path": str(dest),
                    "sha256": digest,
                    "reload": "pending",
                    "codegen": codegen,
                    "warning": (
                        "AGENT_PLUGINS_ALLOWED_SHA256 is set — this file is NOT loaded until the operator "
                        "adds the sha256 above to that env var (comma-separated) and calls "
                        "POST /v1/admin/reload-plugins or restarts the container."
                    ),
                },
                ensure_ascii=False,
            )

    try:
        reload_registry(scope="all")
    except Exception as e:
        logger.exception("reload after create_tool failed")
        return json.dumps(
            {
                "ok": True,
                "written": fn,
                "path": str(dest),
                "sha256": digest,
                "reload": "failed",
                "error": str(e),
                "codegen": codegen,
                "hint": "Fix the plugin or remove the file, then POST /v1/admin/reload-plugins",
            },
            ensure_ascii=False,
        )

    reg = get_registry()
    out: dict[str, Any] = {
        "ok": True,
        "written": fn,
        "path": str(dest),
        "sha256": digest,
        "reload": "ok",
        "codegen": codegen,
        "plugin_file_entries": len(
            [m for m in reg.plugins_meta if "file:" in str(m.get("source", ""))]
        ),
        "hint": "New tools appear in list_available_tools; use get_tool_help for each name.",
    }
    if codegen_model:
        out["codegen_model"] = codegen_model

    if test_tool_name:
        from app.tools import run_tool

        probe = run_tool(test_tool_name, _coerce_test_args(arguments.get("test_arguments")))
        out["test_tool"] = {"name": test_tool_name, "result": probe}

    return json.dumps(out, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "create_tool": create_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_tool",
            "description": (
                "Create a new extra plugin (.py with TOOLS + HANDLERS). Two modes: "
                "(1) Full control: pass filename + source. "
                "(2) Short idea only: omit source, set tool_name (e.g. fishingIndex) — server asks Ollama to write "
                f"{config.PLUGINS_EXTRA_DIR or 'AGENT_PLUGINS_EXTRA_DIR'}/<snake>.py, reloads the registry, "
                "and runs one probe call on the new tool. "
                "Requires AGENT_CREATE_TOOL_ENABLED=true, writable AGENT_PLUGINS_EXTRA_DIR, Ollama reachable. "
                "Optional description for codegen. Same risks as arbitrary Python — trusted networks only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": (
                            "When source is omitted: short name or idea (e.g. fishingIndex). "
                            "Becomes OpenAI tool name snake_case and file <snake>.py."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": "Alias for tool_name when using codegen (omit source).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional extra instructions for codegen (e.g. Beißindex 0–10, heuristics only).",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Basename only when passing source, e.g. my_plugin.py",
                    },
                    "source": {
                        "type": "string",
                        "description": "Full UTF-8 module text. If omitted, server generates via Ollama (tool_name required).",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "If true, replace an existing file of the same name (default false).",
                    },
                    "test_arguments": {
                        "type": "object",
                        "description": "Optional JSON object for the automatic probe call after codegen reload.",
                    },
                },
            },
        },
    },
]
