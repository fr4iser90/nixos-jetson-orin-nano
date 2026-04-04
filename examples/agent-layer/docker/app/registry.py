"""Load tool plugins only from configured directories (``*.py`` files); no package hardcoding."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from . import config
from . import db

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]


def _openai_spec_tool_name(spec: Any) -> str | None:
    if not isinstance(spec, dict):
        return None
    fn = spec.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


def _path_under_or_equal(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _iter_plugin_py_files(root: Path) -> list[Path]:
    """All ``*.py`` under ``root`` (recursive), excluding ``__init__.py``, ``_*``, ``__pycache__``."""
    out: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        out.append(path)
    return out


def _stable_module_slug(directory: Path, path: Path, dir_idx: int) -> str:
    """Unique import-safe suffix for ``spec_from_file_location`` (avoids stem collisions across subdirs)."""
    try:
        rel = path.resolve().relative_to(directory.resolve())
    except (ValueError, OSError):
        rel = Path(path.name)
    rel_no_suffix = rel.with_suffix("")
    parts = [re.sub(r"[^a-zA-Z0-9_]", "_", str(p)) for p in rel_no_suffix.parts]
    slug = "_".join(p for p in parts if p).strip("_") or "plugin"
    if slug and slug[0].isdigit():
        slug = f"m_{slug}"
    return f"{dir_idx}_{slug}"


class ToolRegistry:
    """Scans ``AGENT_PLUGIN_DIRS`` or default ``app/plugins`` + optional extra mount."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, Handler] = {}
        self._openai_tools: list[dict[str, Any]] = []
        self._plugins_meta: list[dict[str, Any]] = []

    def load_all(self) -> None:
        with self._lock:
            self._clear_storage()
            self._purge_dynamic_plugin_modules()
            acc_h: dict[str, Handler] = {}
            acc_tools: list[dict[str, Any]] = []
            acc_meta: list[dict[str, Any]] = []

            allow = config.plugins_allowed_sha256()
            extra_raw = (config.PLUGINS_EXTRA_DIR or "").strip()
            extra_root: Path | None = None
            if extra_raw:
                try:
                    extra_root = Path(extra_raw).expanduser().resolve()
                except OSError:
                    extra_root = Path(extra_raw).expanduser()

            dirs = config.plugin_scan_directories()
            if not dirs:
                logger.warning("no plugin directories to scan (set AGENT_PLUGIN_DIRS or ship app/plugins)")

            for dir_idx, directory in enumerate(dirs):
                if not directory.is_dir():
                    logger.warning("skip missing plugin directory: %s", directory)
                    continue
                for path in _iter_plugin_py_files(directory):
                    try:
                        data = path.read_bytes()
                    except OSError:
                        logger.exception("cannot read plugin file %s", path)
                        continue
                    digest = hashlib.sha256(data).hexdigest()
                    try:
                        path_r = path.resolve()
                    except OSError:
                        path_r = path
                    needs_sha = (
                        allow is not None
                        and extra_root is not None
                        and extra_root.is_dir()
                        and _path_under_or_equal(path_r, extra_root)
                    )
                    if needs_sha and digest not in allow:
                        logger.error(
                            "rejecting plugin (not in AGENT_PLUGINS_ALLOWED_SHA256): %s",
                            path,
                        )
                        continue
                    slug = _stable_module_slug(directory, path, dir_idx)
                    mod_name = f"agent_plugin_{slug}"
                    try:
                        spec = importlib.util.spec_from_file_location(mod_name, path)
                        if spec is None or spec.loader is None:
                            logger.error("cannot load plugin spec: %s", path)
                            continue
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = mod
                        spec.loader.exec_module(mod)
                    except Exception:
                        logger.exception("failed to load plugin %s", path)
                        continue
                    self._register_module(
                        mod,
                        source=f"file:{path}",
                        handlers=acc_h,
                        tools=acc_tools,
                        meta=acc_meta,
                        file_sha256=digest,
                    )

            self._handlers = acc_h
            self._openai_tools = acc_tools
            self._plugins_meta = acc_meta

    def _clear_storage(self) -> None:
        self._handlers.clear()
        self._openai_tools.clear()
        self._plugins_meta.clear()

    def _purge_dynamic_plugin_modules(self) -> None:
        for key in list(sys.modules):
            if key.startswith("agent_plugin_"):
                del sys.modules[key]

    def _register_module(
        self,
        mod: Any,
        source: str,
        handlers: dict[str, Handler],
        tools: list[dict[str, Any]],
        meta: list[dict[str, Any]],
        *,
        file_sha256: str | None = None,
    ) -> None:
        mod_tools = getattr(mod, "TOOLS", None)
        mod_handlers = getattr(mod, "HANDLERS", None)
        if mod_tools is None and mod_handlers is None:
            return
        if not isinstance(mod_tools, list) or not isinstance(mod_handlers, dict):
            logger.error(
                "invalid plugin exports (need TOOLS list and HANDLERS dict): %s", source
            )
            return

        pid = getattr(mod, "PLUGIN_ID", None) or getattr(mod, "__name__", "unknown")
        ver = str(getattr(mod, "__version__", "0"))
        tool_names: list[str] = []
        pending_handlers: dict[str, Handler] = {}
        pending_specs: list[dict[str, Any]] = []

        for spec in mod_tools:
            if not isinstance(spec, dict):
                continue
            fn = spec.get("function") or {}
            name = fn.get("name")
            if not name:
                logger.warning("skip tool without name in %s", source)
                continue
            if name in handlers or name in pending_handlers:
                logger.warning(
                    "skip duplicate tool %r in %s (earlier plugin wins)",
                    name,
                    source,
                )
                continue
            handler = mod_handlers.get(name)
            if not callable(handler):
                logger.error(
                    "skip tool %r in %s: no callable handler in HANDLERS",
                    name,
                    source,
                )
                continue
            pending_handlers[name] = handler  # type: ignore[assignment]
            pending_specs.append(spec)
            tool_names.append(name)

        handlers.update(pending_handlers)
        tools.extend(pending_specs)

        if not tool_names:
            if mod_handlers:
                logger.warning(
                    "plugin %s exports HANDLERS but no valid TOOLS entries",
                    source,
                )
            return

        for declared in mod_handlers:
            if declared not in tool_names:
                logger.warning(
                    "plugin %s declares handler %r without matching TOOLS entry",
                    source,
                    declared,
                )

        entry: dict[str, Any] = {
            "id": pid,
            "version": ver,
            "source": source,
            "tools": tool_names,
        }
        if file_sha256 is not None:
            entry["sha256"] = file_sha256
        meta.append(entry)
        logger.info(
            "loaded plugin %s v%s (%d tools) [%s]", pid, ver, len(tool_names), source
        )

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._openai_tools)

    @property
    def plugins_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._plugins_meta)

    def run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        with self._lock:
            handler = self._handlers.get(name)
        if not handler:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
        ok = True
        try:
            out = handler(dict(arguments or {}))
            payload = json.loads(out) if out else {}
            if isinstance(payload, dict) and payload.get("ok") is False:
                ok = False
        except Exception as e:
            ok = False
            out = json.dumps({"ok": False, "error": str(e)})
        db.log_tool_invocation(name, dict(arguments or {}), out, ok)
        return out


_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ToolRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ToolRegistry()
            _registry.load_all()
        return _registry


def reload_registry(scope: str = "all") -> ToolRegistry:
    """Full rescan of plugin directories. ``scope`` is kept for API compatibility only."""
    global _registry
    s = (scope or "all").strip().lower()
    if s not in ("all", "extra"):
        raise ValueError("scope must be 'all' or 'extra'")

    with _registry_lock:
        candidate = ToolRegistry()
        candidate.load_all()
        _registry = candidate
        return _registry
