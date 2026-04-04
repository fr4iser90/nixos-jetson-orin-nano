"""HTTP routes for tool schemas and plugin registry admin (no per-tool hardcoding)."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from . import config
from .registry import get_registry, reload_registry

logger = logging.getLogger(__name__)

router = APIRouter()


def _openai_tool_name(spec: dict) -> str | None:
    fn = spec.get("function") if isinstance(spec, dict) else None
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


@router.get("/v1/tools")
async def list_tools():
    """Schemas from the live registry (every ``*.py`` under configured plugin dirs)."""
    reg = get_registry()
    return {"tools": reg.openai_tools, "plugins": reg.plugins_meta}


@router.get("/v1/admin/plugins")
async def admin_list_plugins():
    """Plugin metadata only (id, version, source, tool names)."""
    reg = get_registry()
    return {"plugins": reg.plugins_meta}


@router.post("/v1/admin/reload-plugins")
async def admin_reload_plugins(scope: Literal["all", "extra"] = "all"):
    """
    Rescan all configured plugin directories (``AGENT_PLUGIN_DIRS`` or defaults).
    Broken or conflicting plugins are skipped with logs. ``scope`` is accepted for API
    compatibility; both values perform the same full rescan.
    """
    if not config.OPTIONAL_API_KEY:
        logger.warning(
            "reload-plugins called with AGENT_API_KEY unset — consider setting it if exposed"
        )
    try:
        reg = reload_registry(scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("reload-plugins failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    names = [_openai_tool_name(t) for t in reg.openai_tools]
    return {
        "ok": True,
        "scope": scope,
        "plugins": reg.plugins_meta,
        "tool_count": len(reg.openai_tools),
        "tool_names": [n for n in names if n],
    }
