"""Tool subsetting by mode (plugin_factory / workspace / default_chat / full) + optional router + retry narrowing."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Built-in dynamic-plugin tools (file under AGENT_PLUGINS_EXTRA_DIR).
PLUGIN_FACTORY_CORE: frozenset[str] = frozenset(
    {
        "create_tool",
        "list_tools",
        "read_tool",
        "update_tool",
        "replace_tool",
        "rename_tool",
    }
)

TOOL_INTROSPECTION: frozenset[str] = frozenset({"list_available_tools", "get_tool_help"})

VALID_MODES = frozenset({"full", "plugin_factory", "workspace", "default_chat", "default"})


def normalize_mode(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s == "default":
        return "default_chat"
    if s in VALID_MODES and s != "default":
        return s
    return "full"


def _tool_name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    fn = entry.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


def filter_tools_for_mode(
    tools: list[Any],
    mode: str,
    *,
    plugin_factory_includes_help: bool,
) -> list[Any]:
    """Return a filtered copy of OpenAI-style tool specs."""
    m = normalize_mode(mode)
    if m == "full" or not tools:
        return list(tools)

    out: list[Any] = []
    for spec in tools:
        name = _tool_name(spec)
        if not name:
            out.append(spec)
            continue
        if m == "plugin_factory":
            allow = set(PLUGIN_FACTORY_CORE)
            if plugin_factory_includes_help:
                allow |= TOOL_INTROSPECTION
            if name in allow:
                out.append(spec)
        elif m == "workspace":
            if name.startswith("workspace_"):
                out.append(spec)
        elif m == "default_chat":
            if name not in PLUGIN_FACTORY_CORE and not name.startswith("workspace_"):
                out.append(spec)
        else:
            out.append(spec)
    return out


def apply_weak_model_tool_strip(
    tools: list[Any],
    model: str | None,
    *,
    substrings: list[str],
    exclude_names: frozenset[str],
) -> list[Any]:
    """
    Remove tool specs whose OpenAI ``name`` is in ``exclude_names`` when ``model`` matches a weak substring.

    Used in ``plugin_factory`` mode so tiny models are nudged toward ``replace_tool`` / ``create_tool``.
    """
    if not tools or not model or not substrings or not exclude_names:
        return list(tools)
    ml = str(model).lower()
    if not any(s in ml for s in substrings):
        return list(tools)
    out: list[Any] = []
    dropped: list[str] = []
    for spec in tools:
        name = _tool_name(spec)
        if name and name in exclude_names:
            dropped.append(name)
            continue
        out.append(spec)
    if dropped:
        logger.info(
            "weak-model tool strip (model id matches %s): removed %s",
            substrings,
            dropped,
        )
    return out


def last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        c = msg.get("content")
        if isinstance(c, str) and c.strip():
            return c
        if isinstance(c, list):
            parts: list[str] = []
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                    parts.append(p["text"])
            if parts:
                return "\n".join(parts)
    return ""


def classify_mode_by_keywords(
    text: str,
    *,
    plugin_substrings: list[str],
    workspace_substrings: list[str],
) -> str | None:
    if not text.strip():
        return None
    tl = text.lower()
    p_hit = any(s.strip() and s.strip().lower() in tl for s in plugin_substrings if s.strip())
    w_hit = any(s.strip() and s.strip().lower() in tl for s in workspace_substrings if s.strip())
    if p_hit and w_hit:
        return None
    if p_hit:
        return "plugin_factory"
    if w_hit:
        return "workspace"
    return None


def _extract_json_mode(text: str) -> str | None:
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for i in range(1, len(parts), 2):
            block = parts[i].strip()
            if block.lower().startswith("json"):
                block = block[4:].lstrip()
            try:
                o = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict) and isinstance(o.get("mode"), str):
                return normalize_mode(o["mode"])
    try:
        o = json.loads(t)
        if isinstance(o, dict) and isinstance(o.get("mode"), str):
            return normalize_mode(o["mode"])
    except json.JSONDecodeError:
        pass
    m = re.search(r'"mode"\s*:\s*"([^"]+)"', t)
    if m:
        return normalize_mode(m.group(1))
    return None


async def classify_mode_by_llm(
    *,
    user_text: str,
    model: str,
    ollama_base: str,
) -> str | None:
    """Single classification call; returns a valid mode or None."""
    if not user_text.strip():
        return None
    import httpx

    system = (
        "You are a router. Reply with ONE JSON object only, no markdown, no prose. "
        'Schema: {"mode":"<one of: full, plugin_factory, workspace, default_chat>"}.\n'
        "plugin_factory: user edits/creates Python agent plugins under the extra plugin directory "
        "(create_tool, read_tool, update_tool, replace_tool, dynamic tools).\n"
        "workspace: user edits files in the mounted workspace (workspace_* tools only).\n"
        "default_chat: normal chat, todos, web, email, github, kb — no plugin file authoring, no workspace files.\n"
        "full: unclear or needs everything.\n"
    )
    user = f"Classify this user message:\n{user_text[:6000]}"
    url = f"{ollama_base.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("tool router LLM failed: %s", e)
        return None
    choice0 = (data.get("choices") or [{}])[0]
    msg = choice0.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        return None
    mode = _extract_json_mode(content)
    if mode in ("plugin_factory", "workspace", "default_chat", "full"):
        return mode
    return None


def workspace_error_suggests_plugin_path(result: str) -> bool:
    """True if a workspace_* tool failed because workspace is not configured."""
    s = (result or "").lower()
    needles = (
        "local workspace tools are disabled",
        "agent_workspace_root",
        "workspace root",
        "workspace isn't set up",
        "workspace is not configured",
        "disabled until agent_workspace_root",
    )
    return any(n in s for n in needles)


def should_narrow_after_tool_result(tool_name: str, result: str) -> bool:
    return bool(
        tool_name.startswith("workspace_")
        and workspace_error_suggests_plugin_path(result)
    )
