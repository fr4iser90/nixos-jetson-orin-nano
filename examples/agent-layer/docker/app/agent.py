"""Chat completion with tool-call loop against Ollama OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import re
import uuid
from json import JSONDecoder
from typing import Any

import httpx

from . import config
from .registry import get_registry
from .tool_routing import (
    apply_weak_model_tool_strip,
    classify_mode_by_keywords,
    classify_mode_by_llm,
    filter_tools_for_mode,
    last_user_text,
    normalize_mode,
    should_narrow_after_tool_result,
)
from .tools import run_tool

logger = logging.getLogger(__name__)


def _chat_model_matches_weak_substrings(model_id: str | None) -> bool:
    if not model_id:
        return False
    subs = config.AGENT_WEAK_TOOL_MODEL_SUBSTRINGS
    if not subs:
        return False
    ml = str(model_id).lower()
    return any(s in ml for s in subs)


def _http_error_recovery_hint(
    tool_name: str, result: str, *, chat_model: str | None = None
) -> str | None:
    if not config.AGENT_TOOL_HTTP_ERROR_RECOVERY_HINTS:
        return None
    if len(result) > 8000:
        return None
    rl = result.lower()
    markers = (
        "http error",
        "bad request",
        "401 unauthorized",
        "403 forbidden",
        "404 not found",
        " 400 ",
        "'400'",
        '"400"',
        "status 400",
        "status 401",
        "status 403",
        "status 404",
        "httpx",
        "for url 'http",
        'for url "http',
    )
    if not any(m in rl for m in markers):
        return None
    weak = _chat_model_matches_weak_substrings(chat_model)
    if weak:
        fix_strategy = (
            "With this **small chat model**, prefer **`replace_tool`** with full `source` after you see the bug "
            "(narrow `update_tool` patches are easy to get wrong). "
        )
    else:
        fix_strategy = (
            "For a **one-line API fix** (wrong query param, URL), **`update_tool`** is usually enough; "
            "use **`replace_tool`** if you need a larger rewrite. "
        )
    return (
        "The previous tool output suggests an HTTP/API failure. "
        "Do not blame the API key first: **400 Bad Request** often means **wrong query parameters** "
        "(e.g. OpenWeather `/data/2.5/weather` expects **`q`** for the place name, not `city`). "
        "**401** more often means an invalid or missing key. "
        + fix_strategy
        + "Next steps: (1) **`read_tool`** the `.py` for this tool (use `openai_tool_name` "
        f"{tool_name!r} or `filename`). (2) Optionally **`search_web`** for the vendor's current API docs. "
        "(3) Apply the fix with **`replace_tool`** and/or **`update_tool`**; use **`https://`**. "
        "(4) Or delegate to built-ins: **`invoke_registered_tool`**(`\"openweather_current\"`, "
        "`{\"location\": \"…\"}`) / `openweather_forecast` from Python in an extra tool."
    )


# Substrings for keyword router when env lists are empty (conservative on "workspace").
_DEFAULT_ROUTER_TOOL_SUBSTRINGS = [
    "create_tool",
    "read_tool",
    "update_tool",
    "replace_tool",
    "rename_tool",
    "list_tools",
    "/data/tools",
    "extra_tools",
    "tool_factory",
    "openai_tool_name",
    "dynamic tool",
    "AGENT_TOOLS_EXTRA_DIR",
    "fishing_index",
]
_DEFAULT_ROUTER_WORKSPACE_SUBSTRINGS = [
    "workspace_read_file",
    "workspace_write_file",
    "workspace_replace_text",
    "workspace_list_dir",
    "workspace_stat",
    "workspace_glob",
    "workspace_search_text",
    "AGENT_WORKSPACE_ROOT",
    "gemounteten workspace",
]

_BODY_KEYS_STRIP_FROM_OLLAMA = frozenset(
    {
        "agent_tool_mode",
        "agent_mode",
        "tool_prefetch",
    }
)


def _inject_system_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not config.SYSTEM_PROMPT_EXTRA:
        return messages
    extra = config.SYSTEM_PROMPT_EXTRA
    if not messages:
        return [{"role": "system", "content": extra}]
    out = list(messages)
    if out[0].get("role") == "system":
        existing = out[0].get("content") or ""
        out[0] = {
            **out[0],
            "content": (existing + "\n\n" + extra).strip() if existing else extra,
        }
    else:
        out.insert(0, {"role": "system", "content": extra})
    return out


def _tool_spec_name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    fn = entry.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


def _merge_tools(body_tools: list[Any] | None) -> list[Any]:
    """
    Always merge the live registry tool list into the request for Ollama.

    Open WebUI often sends its own non-empty ``tools`` list; previously that
    replaced our list entirely so the model never saw agent-layer tools.
    """
    ours = get_registry().openai_tools
    if not body_tools:
        return ours
    seen = {n for t in ours if (n := _tool_spec_name(t))}
    merged: list[Any] = list(ours)
    for t in body_tools:
        if not isinstance(t, dict):
            continue
        n = _tool_spec_name(t)
        if n is None:
            merged.append(t)
            continue
        if n not in seen:
            merged.append(t)
            seen.add(n)
    logger.debug(
        "tools merge: registry=%d client=%d merged=%d",
        len(ours),
        len(body_tools),
        len(merged),
    )
    return merged


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid tool arguments JSON: %s", raw[:200])
        return {}


def _unwrap_fenced_json(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if not lines:
        return t
    lines = lines[1:]
    while lines and lines[-1].strip() in ("```", ""):
        lines.pop()
    return "\n".join(lines).strip()


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _end = JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _known_tool_names() -> set[str]:
    return {n for t in get_registry().openai_tools if (n := _tool_spec_name(t))}


def _coerce_params_dict(p: Any) -> dict[str, Any] | None:
    if p is None:
        return {}
    if isinstance(p, dict):
        return p
    if isinstance(p, str):
        s = p.strip()
        if not s:
            return {}
        try:
            o = json.loads(s)
        except json.JSONDecodeError:
            return None
        return dict(o) if isinstance(o, dict) else None
    return None


# JSON where the function name is under ``tool_name`` (Nemotron) instead of ``name`` / ``tool``.
_CONTENT_META_TOOL_NAMES = frozenset(
    {
        "read_tool",
        "replace_tool",
        "create_tool",
        "update_tool",
        "rename_tool",
        "list_tools",
        "list_available_tools",
        "get_tool_help",
    }
)


def _parse_tool_intent_from_content(content: str) -> tuple[str, dict[str, Any]] | None:
    """
    Some models emit JSON like {\"tool\": \"<name>\", \"parameters\": {...}} in message content
    instead of OpenAI-style tool_calls.
    """
    obj = _extract_first_json_object(_unwrap_fenced_json(content))
    if not obj:
        return None
    name: str | None = None
    params: dict[str, Any] | None = None
    tnk = obj.get("tool_name")
    if isinstance(tnk, str) and tnk.strip() in _CONTENT_META_TOOL_NAMES:
        name = tnk.strip()
        params = {k: v for k, v in obj.items() if k != "tool_name"}
        return name, params
    if isinstance(obj.get("tool"), str):
        name = obj["tool"]
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        params = _coerce_params_dict(p)
    elif isinstance(obj.get("name"), str):
        name = obj["name"]
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        params = _coerce_params_dict(p)
    elif isinstance(obj.get("function"), str):
        name = obj["function"]
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        params = _coerce_params_dict(p)
    if not name or params is None:
        return None
    return name, params


def _content_fallback_args_acceptable(name: str, params: dict[str, Any]) -> bool:
    """Reject synthetic tool_calls that would no-op or loop (e.g. read_tool({}))."""
    if name == "read_tool":
        return any(str(params.get(k) or "").strip() for k in ("filename", "openai_tool_name", "tool_name", "name"))
    if name == "replace_tool":
        if not str(params.get("source") or "").strip():
            return False
        return any(str(params.get(k) or "").strip() for k in ("filename", "openai_tool_name", "tool_name", "name"))
    if name == "update_tool":
        if not str(params.get("old_string") or "").strip():
            return False
        return any(str(params.get(k) or "").strip() for k in ("filename", "openai_tool_name", "tool_name", "name"))
    if name == "create_tool":
        if str(params.get("source") or "").strip():
            return True
        return bool(str(params.get("tool_name") or "").strip() or str(params.get("name") or "").strip())
    if name == "rename_tool":
        return bool(str(params.get("old_filename") or "").strip()) and bool(
            str(params.get("new_filename") or "").strip()
        )
    if name == "get_tool_help":
        return bool(str(params.get("tool_name") or "").strip())
    return True


def _text_blobs_from_message(msg: dict[str, Any]) -> list[str]:
    """Collect strings where models may hide JSON tool intent (reasoning models, multimodal content)."""
    blobs: list[str] = []
    t = msg.get("text")
    if isinstance(t, str) and t.strip():
        blobs.append(t)
    c = msg.get("content")
    if isinstance(c, str) and c.strip():
        blobs.append(c)
    elif isinstance(c, list):
        for part in c:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    blobs.append(part["text"])
                elif isinstance(part.get("content"), str):
                    blobs.append(part["content"])
            elif isinstance(part, str):
                blobs.append(part)
    for key in (
        "reasoning_content",
        "reasoning",
        "thinking",
        "thought",
        "reasoning_content_delta",  # some proxies
    ):
        v = msg.get(key)
        if isinstance(v, str) and v.strip():
            blobs.append(v)
    return blobs


def _synthetic_tool_calls_from_message(
    msg: dict[str, Any],
    choice: dict[str, Any] | None = None,
    *,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]] | None:
    if not config.CONTENT_TOOL_FALLBACK:
        return None
    if msg.get("tool_calls"):
        return None
    known = allowed_tool_names if allowed_tool_names is not None else _known_tool_names()
    blobs = _text_blobs_from_message(msg)
    if choice:
        for key in ("thought", "reasoning", "thinking"):
            v = choice.get(key)
            if isinstance(v, str) and v.strip():
                blobs.append(v)
    for blob in blobs:
        parsed = _parse_tool_intent_from_content(blob)
        if not parsed:
            continue
        name, params = parsed
        if name not in known:
            logger.debug("content tool JSON names unknown tool %r, ignoring", name)
            continue
        if not _content_fallback_args_acceptable(name, params):
            logger.info(
                "content tool fallback: reject %s with insufficient args %r (avoid empty read_tool loop)",
                name,
                params,
            )
            continue
        tc = {
            "id": f"content-{uuid.uuid4().hex[:16]}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(params)},
        }
        logger.info(
            "content tool fallback: treating assistant JSON as tool_calls for %s(%s)",
            name,
            params,
        )
        return [tc]
    logger.debug(
        "content tool fallback: no tool JSON found (message keys=%s, blobs=%d)",
        list(msg.keys()),
        len(blobs),
    )
    return None


def _router_tool_substrings() -> list[str]:
    raw = config.AGENT_TOOL_ROUTER_KEYWORDS_TOOL_FACTORY
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(_DEFAULT_ROUTER_TOOL_SUBSTRINGS)


def _router_workspace_substrings() -> list[str]:
    raw = config.AGENT_TOOL_ROUTER_KEYWORDS_WORKSPACE
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(_DEFAULT_ROUTER_WORKSPACE_SUBSTRINGS)


async def _resolve_tool_mode(body: dict[str, Any], *, chat_model: str) -> str:
    raw = (body.get("agent_tool_mode") or body.get("agent_mode") or "").strip()
    if raw:
        return normalize_mode(raw)

    messages = list(body.get("messages") or [])
    ut = last_user_text(messages)
    if config.AGENT_TOOL_ROUTER_KEYWORDS_ENABLED and ut:
        kw = classify_mode_by_keywords(
            ut,
            tool_substrings=_router_tool_substrings(),
            workspace_substrings=_router_workspace_substrings(),
        )
        if kw:
            logger.info("tool router (keywords): mode=%s", kw)
            return kw

    if config.AGENT_TOOL_ROUTER_LLM_ENABLED and ut:
        rm = (config.AGENT_TOOL_ROUTER_MODEL or "").strip() or chat_model
        m = await classify_mode_by_llm(
            user_text=ut,
            model=rm,
            ollama_base=config.OLLAMA_BASE_URL,
        )
        if m:
            logger.info("tool router (LLM): mode=%s", m)
            return m

    return normalize_mode(config.AGENT_TOOL_MODE)


def _apply_tool_prefetch(messages: list[dict[str, Any]], prefetch: dict[str, Any]) -> None:
    args = {
        k: prefetch[k]
        for k in ("filename", "openai_tool_name", "tool_name", "name")
        if k in prefetch and prefetch[k] is not None and str(prefetch[k]).strip()
    }
    if not args:
        return
    snippet = run_tool("read_tool", args)
    try:
        o = json.loads(snippet)
    except json.JSONDecodeError:
        o = {}
    if isinstance(o, dict) and o.get("ok") is True:
        src = str(o.get("source") or "")
        max_c = min(len(src), config.CREATE_TOOL_MAX_BYTES)
        block = (
            "Server prefetch via read_tool — edit this **extra-tool module** with read_tool/update_tool/replace_tool "
            "(not workspace_*).\n\n"
            f"File: `{o.get('filename')}`\n\n```python\n{src[:max_c]}\n```"
        )
    else:
        err = o.get("error") if isinstance(o, dict) else snippet[:500]
        block = f"Server prefetch read_tool failed: {err}"
    if not messages:
        messages.append({"role": "system", "content": block})
        return
    if messages[0].get("role") == "system":
        prev = messages[0].get("content") or ""
        messages[0] = {
            **messages[0],
            "content": (block + "\n\n" + prev).strip() if prev else block,
        }
    else:
        messages.insert(0, {"role": "system", "content": block})


def _inject_tool_factory_tool_hint(messages: list[dict[str, Any]]) -> None:
    """Steer small models away from inventing JSON keys like replace_source instead of real tool_calls."""
    hint = (
        "[tool_factory] After read_tool you must call a real tool from the schema (OpenAI tool_calls), "
        "not arbitrary JSON in the reply text. "
        "Prefer replace_tool: openai_tool_name or filename plus source (complete valid Python module). "
        "update_tool may be unavailable for small chat models — use replace_tool for full rewrites. "
        "Patch-style edits need exact old_string snippets. "
        "No parameter or tool named replace_source."
    )
    if not messages:
        messages.append({"role": "system", "content": hint})
        return
    if messages[0].get("role") == "system":
        prev = messages[0].get("content") or ""
        messages[0] = {
            **messages[0],
            "content": (hint + "\n\n" + prev).strip() if prev else hint,
        }
    else:
        messages.insert(0, {"role": "system", "content": hint})


def _names_from_tool_list(tools: list[Any]) -> set[str]:
    return {n for t in tools if (n := _tool_spec_name(t))}


def _tools_for_round(
    merged_tools: list[Any],
    active_mode: str,
    model: Any,
) -> list[Any]:
    tfr = filter_tools_for_mode(
        merged_tools,
        active_mode,
        tool_factory_includes_help=config.AGENT_TOOL_MODE_TOOL_FACTORY_INCLUDES_HELP,
    )
    if normalize_mode(active_mode) == "tool_factory":
        tfr = apply_weak_model_tool_strip(
            tfr,
            str(model) if model is not None else "",
            substrings=config.AGENT_WEAK_TOOL_MODEL_SUBSTRINGS,
            exclude_names=config.AGENT_WEAK_TOOL_MODEL_EXCLUDE_TOOLS,
        )
    return tfr


def _approx_text_chars_in_messages(messages: list[dict[str, Any]]) -> int:
    return sum(sum(len(b) for b in _text_blobs_from_message(m)) for m in messages)


def _redact_secrets_for_log(s: str) -> str:
    """Best-effort masking for log previews (OpenWeather appid, Bearer tokens)."""
    s = re.sub(r"(?i)appid=[A-Za-z0-9._-]+", "appid=***", s)
    s = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer ***", s)
    return s


def _log_ollama_round(
    *,
    round_i: int,
    model: Any,
    messages: list[dict[str, Any]],
    tools_for_round: list[Any],
    msg: dict[str, Any],
    choice0: dict[str, Any],
    tool_calls: list[Any] | None,
    had_native_tool_calls: bool,
) -> None:
    if not config.AGENT_LOG_LLM_ROUNDS:
        return
    ctx_msgs = len(messages)
    ctx_chars = _approx_text_chars_in_messages(messages)
    large = ""
    if ctx_chars >= config.AGENT_LOG_LARGE_CONTEXT_CHARS:
        large = f" LARGE_CTX(>={config.AGENT_LOG_LARGE_CONTEXT_CHARS} chars)"
    rt_names = [n for t in (tools_for_round or []) if (n := _tool_spec_name(t))]
    syn = bool(tool_calls) and not had_native_tool_calls
    if tool_calls:
        call_names = [(tc.get("function") or {}).get("name") or "?" for tc in tool_calls]
        logger.info(
            "llm round %d/%d model=%s reply=TOOLS calls=%s content_json_fallback=%s "
            "ctx_msgs=%d ctx_text_chars~=%d ollama_tool_defs=%d tool_names=%s%s",
            round_i + 1,
            config.MAX_TOOL_ROUNDS,
            model,
            call_names,
            syn,
            ctx_msgs,
            ctx_chars,
            len(rt_names),
            rt_names,
            large,
        )
        return
    cap = config.AGENT_LOG_ASSISTANT_PREVIEW_CHARS
    blobs = list(_text_blobs_from_message(msg))
    for key in ("thought", "reasoning", "thinking"):
        v = choice0.get(key)
        if isinstance(v, str) and v.strip():
            blobs.append(v)
    joined = "\n".join(blobs)
    any_text = bool(joined.strip())
    if cap > 0:
        preview = _redact_secrets_for_log(joined[:cap])
    else:
        preview = "(set AGENT_LOG_ASSISTANT_PREVIEW_CHARS>0 for redacted snippet)"
    if not any_text:
        logfn = logger.warning if rt_names else logger.info
        logfn(
            "llm round %d/%d model=%s reply=EMPTY_NO_TOOLS content_json_fallback=%s "
            "ctx_msgs=%d ctx_text_chars~=%d ollama_tool_defs=%d%s",
            round_i + 1,
            config.MAX_TOOL_ROUNDS,
            model,
            syn,
            ctx_msgs,
            ctx_chars,
            len(rt_names),
            large,
        )
        return
    logger.info(
        "llm round %d/%d model=%s reply=TEXT_NO_TOOLS content_json_fallback=%s "
        "ctx_msgs=%d ctx_text_chars~=%d ollama_tool_defs=%d preview=%r%s",
        round_i + 1,
        config.MAX_TOOL_ROUNDS,
        model,
        syn,
        ctx_msgs,
        ctx_chars,
        len(rt_names),
        preview,
        large,
    )


async def chat_completion(body: dict[str, Any]) -> dict[str, Any]:
    # stream flag is ignored here; Ollama always gets stream=false. Caller may wrap JSON as SSE.
    model = body.get("model")
    if not model:
        raise ValueError("missing model")

    messages = _inject_system_prompt(list(body.get("messages") or []))
    pf = body.get("tool_prefetch")
    if isinstance(pf, dict):
        _apply_tool_prefetch(messages, pf)

    tool_mode = await _resolve_tool_mode(body, chat_model=str(model))
    if tool_mode == "tool_factory":
        _inject_tool_factory_tool_hint(messages)

    merged_tools = _merge_tools(body.get("tools"))
    tools = _tools_for_round(merged_tools, tool_mode, model)
    narrow_mode: str | None = None

    if tools:
        names = [n for t in tools if (n := _tool_spec_name(t))]
        logger.info(
            "forwarding %d tools to Ollama (mode=%s, model=%s): %s",
            len(names),
            tool_mode,
            model,
            names,
        )
    options = {
        k: v
        for k, v in body.items()
        if k not in ("messages", "model", "tools", "stream", *_BODY_KEYS_STRIP_FROM_OLLAMA)
    }

    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=600.0) as client:
        for round_i in range(config.MAX_TOOL_ROUNDS):
            active_mode = narrow_mode if narrow_mode else tool_mode
            tools_for_round = _tools_for_round(merged_tools, active_mode, model)
            allowed_names = _names_from_tool_list(tools_for_round)

            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
                **options,
            }
            if tools_for_round:
                payload["tools"] = tools_for_round

            resp = await client.post(url, json=payload, headers=headers)
            if resp.is_error:
                err_body = (resp.text or "")[:4000]
                logger.error(
                    "Ollama chat/completions failed: status=%s model=%s body=%s",
                    resp.status_code,
                    model,
                    err_body or "(empty)",
                )
            resp.raise_for_status()
            data = resp.json()

            choice0 = (data.get("choices") or [{}])[0]
            raw_msg = choice0.get("message")
            if not isinstance(raw_msg, dict):
                raw_msg = {}
            msg = dict(raw_msg)
            raw_tc = msg.get("tool_calls")
            had_native_tool_calls = isinstance(raw_tc, list) and len(raw_tc) > 0
            tool_calls = raw_tc if had_native_tool_calls else None
            if not tool_calls:
                tool_calls = _synthetic_tool_calls_from_message(
                    msg, choice0, allowed_tool_names=allowed_names
                )
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                    choice0["message"] = msg

            _log_ollama_round(
                round_i=round_i,
                model=model,
                messages=messages,
                tools_for_round=tools_for_round,
                msg=msg,
                choice0=choice0 if isinstance(choice0, dict) else {},
                tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                had_native_tool_calls=had_native_tool_calls,
            )

            if not tool_calls:
                return data

            # Append assistant message (includes tool_calls, and content if any)
            messages.append(msg)

            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                args = _parse_tool_arguments(fn.get("arguments"))
                tool_call_id = tc.get("id") or ""
                logger.info("tool round %s: %s(%s)", round_i + 1, name, args)
                result = run_tool(name, args)
                if (
                    config.AGENT_TOOL_RETRY_NARROW_TO_TOOL_FACTORY
                    and narrow_mode is None
                    and should_narrow_after_tool_result(name, result)
                ):
                    narrow_mode = "tool_factory"
                    logger.info(
                        "tool routing: narrowed remaining rounds to tool_factory "
                        "(workspace tool failed; use read_tool/update_tool/replace_tool for /data/tools)"
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Workspace tools are not available in this deployment. "
                                "For Python modules under the extra tool directory, use read_tool, "
                                "update_tool, replace_tool, or create_tool — not workspace_*. "
                                "Call replace_tool with source (full file) or update_tool with old_string/new_string; "
                                "do not reply with invented JSON like replace_source."
                            ),
                        }
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    }
                )
                recovery = _http_error_recovery_hint(name, result, chat_model=str(model))
                if recovery:
                    messages.append({"role": "system", "content": recovery})

        logger.warning(
            "max tool rounds (%s) exceeded ctx_msgs=%d ctx_text_chars~=%d",
            config.MAX_TOOL_ROUNDS,
            len(messages),
            _approx_text_chars_in_messages(messages),
        )
        return data
