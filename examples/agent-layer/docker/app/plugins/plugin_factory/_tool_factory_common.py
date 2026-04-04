"""Shared helpers for plugin_factory tools (not a plugin — ``_*`` skipped by registry scan)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app import config
from app import plugin_authoring
from app.registry import get_registry, reload_registry

logger = logging.getLogger(__name__)


def coerce_test_args(raw: Any) -> dict[str, Any]:
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


def extra_root_or_error() -> tuple[Path | None, str | None]:
    if not config.CREATE_TOOL_ENABLED:
        return None, json.dumps(
            {
                "ok": False,
                "error": (
                    "tool factory is disabled. Set AGENT_CREATE_TOOL_ENABLED=true "
                    "and mount a writable directory (e.g. ./extra_plugins:/data/plugins:rw)."
                ),
            },
            ensure_ascii=False,
        )
    raw = (config.PLUGINS_EXTRA_DIR or "").strip()
    if not raw:
        return None, json.dumps(
            {
                "ok": False,
                "error": (
                    "AGENT_PLUGINS_EXTRA_DIR is empty. With create_tool enabled, default is /data/plugins "
                    "— ensure that path is mounted read-write from the host."
                ),
            },
            ensure_ascii=False,
        )
    root = Path(raw)
    if not root.is_dir():
        return None, json.dumps(
            {"ok": False, "error": f"AGENT_PLUGINS_EXTRA_DIR is not a directory: {raw}"},
            ensure_ascii=False,
        )
    return root, None


def digest_reload_response(
    fn: str,
    dest: Path,
    *,
    codegen: bool = False,
    codegen_model: str | None = None,
    test_tool_name: str | None = None,
    test_arguments: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    allow = config.plugins_allowed_sha256()
    if allow is not None and digest not in allow:
        out: dict[str, Any] = {
            "ok": True,
            "written": fn,
            "path": str(dest),
            "sha256": digest,
            "reload": "pending",
            "codegen": codegen,
            "warning": (
                "AGENT_PLUGINS_ALLOWED_SHA256 is set — file NOT loaded until operator adds sha256 "
                "to env and POST /v1/admin/reload-plugins or restarts."
            ),
        }
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)
    try:
        reload_registry(scope="all")
    except Exception as e:
        logger.exception("reload after tool module change failed")
        out = {
            "ok": True,
            "written": fn,
            "path": str(dest),
            "sha256": digest,
            "reload": "failed",
            "error": str(e),
            "codegen": codegen,
            "hint": "POST /v1/admin/reload-plugins or restart",
        }
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)

    reg = get_registry()
    out = {
        "ok": True,
        "written": fn,
        "path": str(dest),
        "sha256": digest,
        "reload": "ok",
        "codegen": codegen,
        "plugin_file_entries": len(
            [m for m in reg.plugins_meta if "file:" in str(m.get("source", ""))]
        ),
        "hint": "Use list_available_tools; read_tool, update_tool (patch), or replace_tool (full file).",
    }
    if codegen_model:
        out["codegen_model"] = codegen_model
    if extra:
        out.update(extra)
    if test_tool_name:
        from app.tools import run_tool

        probe = run_tool(test_tool_name, test_arguments or {})
        out["test_tool"] = {"name": test_tool_name, "result": probe}
    return json.dumps(out, ensure_ascii=False)


def validate_module_text(text: str, fn: str, *, codegen: bool) -> str | None:
    _ = codegen
    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return (
            f"source exceeds AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES}); "
            "raise limit or split the plugin."
        )
    try:
        compile(text, fn, "exec")
    except SyntaxError as e:
        return f"compile failed: {e}"
    ast_err = plugin_authoring.validate_plugin_source(text)
    if ast_err:
        return ast_err
    return plugin_authoring.validate_plugin_registry_exports(text)


def extract_python_from_llm(text: str) -> str:
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


def probe_block_succeeded(test_tool_block: Any) -> bool:
    if not isinstance(test_tool_block, dict):
        return False
    raw = test_tool_block.get("result")
    if not isinstance(raw, str):
        return False
    if "unknown tool" in raw.lower():
        return False
    try:
        o = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if isinstance(o, dict) and o.get("ok") is False:
        return False
    return True


def retry_hint_from_response(out: dict[str, Any]) -> tuple[bool, str]:
    if out.get("ok") is not True:
        return False, ""
    if out.get("reload") != "ok":
        return False, ""
    tt = out.get("test_tool")
    if not isinstance(tt, dict):
        return False, ""
    if probe_block_succeeded(tt):
        return False, ""
    raw = tt.get("result")
    hint = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    return True, hint[:8000]


def ollama_generate_module(
    *,
    openai_tool_name: str,
    display_hint: str,
    extra_description: str,
    repair_context: str | None = None,
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
        "- TOOLS must be a list with EXACTLY this nesting (name goes INSIDE \"function\", never at top level):\n"
        "TOOLS = [\n"
        "    {\n"
        '        "type": "function",\n'
        '        "function": {\n'
        f'            "name": "{openai_tool_name}",\n'
        '            "description": "…",\n'
        '            "parameters": {\n'
        '                "type": "object",\n'
        '                "properties": { ... },\n'
        '                "required": [],\n'
        "            },\n"
        "        },\n"
        "    },\n"
        "]\n\n"
        "Rules:\n"
        f"- Exactly one TOOLS entry; HANDLERS has exactly one key \"{openai_tool_name}\".\n"
    )
    if config.CREATE_TOOL_CODEGEN_ALLOW_NETWORK:
        system += (
            "- HTTP: you MAY use httpx (e.g. httpx.Client(timeout=10.0)) or urllib.request for public APIs. "
            "Never hardcode secrets — only os.environ.get(\"SOME_API_KEY\") etc.; operator sets env in Docker. "
            "Return clear json errors on HTTP failures.\n"
            "- Still forbidden: subprocess, os.system, eval, exec, __import__, reading/writing local files.\n"
        )
    else:
        system += (
            "- No network: implement deterministic heuristics from tool arguments only; state that in the description.\n"
            "- No subprocess, os.system, eval/exec/__import__, no httpx/urllib for HTTP.\n"
        )
    user = (
        f"Implement a plugin for this short name / idea: {display_hint}\n"
        f"OpenAI function name (required, already chosen): {openai_tool_name}\n"
        f"Extra instructions: {extra_description or '(none)'}\n"
    )
    if repair_context:
        user += (
            "\n\n---\nPrevious module failed validation or the automatic test call. "
            "Output one full corrected module (same OpenAI function name). Context:\n"
            + repair_context.strip()
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
    raw = extract_python_from_llm(content)
    if not re.search(r"\bHANDLERS\b", raw) or not re.search(r"\bTOOLS\b", raw):
        return None, "codegen: response does not look like a plugin module"
    return raw, None
