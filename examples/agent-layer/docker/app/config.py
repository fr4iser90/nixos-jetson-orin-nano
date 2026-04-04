import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def normalize_tool_mode(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s == "default":
        return "default_chat"
    if s in ("full", "plugin_factory", "workspace", "default_chat"):
        return s
    return "full"


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    """Parse integer env; empty or whitespace uses ``default`` (Compose often passes ``VAR=``)."""
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return default
    return int(raw)


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
MAX_TOOL_ROUNDS = _env_int("AGENT_MAX_TOOL_ROUNDS", 8)
DATA_DIR = os.environ.get("AGENT_DATA_DIR", "/data")
OPTIONAL_API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
SYSTEM_PROMPT_EXTRA = os.environ.get("AGENT_SYSTEM_PROMPT", "").strip()

# If Ollama returns no tool_calls but JSON tool intent in message content (e.g. Nemotron), parse and run.
CONTENT_TOOL_FALLBACK = _env_bool("AGENT_CONTENT_TOOL_FALLBACK", True)

# --- Tool routing (subset by mode; header X-Agent-Mode overrides) ---
# full | plugin_factory | workspace | default_chat (alias: default)
AGENT_TOOL_MODE = normalize_tool_mode(os.environ.get("AGENT_TOOL_MODE", "full"))

AGENT_TOOL_MODE_PLUGIN_FACTORY_INCLUDES_HELP = _env_bool(
    "AGENT_TOOL_MODE_PLUGIN_FACTORY_INCLUDES_HELP", True
)
# If no X-Agent-Mode / JSON agent_tool_mode: keyword substring match on last user message
AGENT_TOOL_ROUTER_KEYWORDS_ENABLED = _env_bool("AGENT_TOOL_ROUTER_KEYWORDS_ENABLED", True)
# Comma-separated case-insensitive substrings (empty = use built-in defaults in agent)
AGENT_TOOL_ROUTER_KEYWORDS_PLUGIN_FACTORY = os.environ.get(
    "AGENT_TOOL_ROUTER_KEYWORDS_PLUGIN_FACTORY", ""
).strip()
AGENT_TOOL_ROUTER_KEYWORDS_WORKSPACE = os.environ.get(
    "AGENT_TOOL_ROUTER_KEYWORDS_WORKSPACE", ""
).strip()
# Optional second stage: one short Ollama call when keywords are inconclusive
AGENT_TOOL_ROUTER_LLM_ENABLED = _env_bool("AGENT_TOOL_ROUTER_LLM_ENABLED", False)
AGENT_TOOL_ROUTER_MODEL = (os.environ.get("AGENT_TOOL_ROUTER_MODEL") or "").strip()
# After workspace_* fails with "disabled", narrow remaining rounds to plugin_factory tools
AGENT_TOOL_RETRY_NARROW_TO_PLUGIN_FACTORY = _env_bool(
    "AGENT_TOOL_RETRY_NARROW_TO_PLUGIN_FACTORY", True
)

# In plugin_factory mode: if chat ``model`` id contains any substring (case-insensitive), drop listed tools.
# Small models fail at exact old_string patches; replace_tool / create_tool work better.
def _weak_tool_model_substrings() -> list[str]:
    raw = (os.environ.get("AGENT_WEAK_TOOL_MODEL_SUBSTRINGS") or "nemotron,nano").strip()
    if not raw:
        return []
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _weak_tool_model_exclude_names() -> frozenset[str]:
    raw = (os.environ.get("AGENT_WEAK_TOOL_MODEL_EXCLUDE_TOOLS") or "update_tool").strip()
    if not raw:
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


AGENT_WEAK_TOOL_MODEL_SUBSTRINGS = _weak_tool_model_substrings()
AGENT_WEAK_TOOL_MODEL_EXCLUDE_TOOLS = _weak_tool_model_exclude_names()


def _resolve_database_url() -> str:
    """
    Prefer explicit DATABASE_URL. If unset/empty, build from POSTGRES_* / PGHOST (same as compose postgres service),
    so the agent starts without duplicating the full URL in compose.yaml.
    """
    direct = os.environ.get("DATABASE_URL", "").strip()
    if direct:
        return direct
    user = (os.environ.get("POSTGRES_USER") or "agent").strip()
    dbn = (os.environ.get("POSTGRES_DB") or "agent").strip()
    if not user or not dbn:
        return ""
    raw_pw = os.environ.get("POSTGRES_PASSWORD")
    password = "agent" if raw_pw is None else str(raw_pw)
    host = (
        os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST") or "postgres"
    ).strip() or "postgres"
    port = (os.environ.get("PGPORT") or "5432").strip() or "5432"
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(dbn)}"
    )


# postgresql://USER:PASSWORD@HOST:5432/DBNAME
DATABASE_URL = _resolve_database_url()

# Extra plugin tree (optional): scan + create_tool writes here. Two different concerns:
# - ENABLE = whether create_tool may run (security / ops).
# - DIR = filesystem path (must exist in the container; Docker still needs a volume mount for a host folder).
# If ENABLE is true and AGENT_PLUGINS_EXTRA_DIR is unset/empty, default /data/plugins (typical compose mount target).
CREATE_TOOL_ENABLED = _env_bool("AGENT_CREATE_TOOL_ENABLED", False)
_PLUGINS_EXTRA_RAW = (os.environ.get("AGENT_PLUGINS_EXTRA_DIR") or "").strip()
PLUGINS_EXTRA_DIR = _PLUGINS_EXTRA_RAW or ("/data/plugins" if CREATE_TOOL_ENABLED else "")


def plugin_scan_directories() -> list[Path]:
    """
    Plugin **roots** to scan **recursively** for ``*.py`` (TOOLS + HANDLERS), including subfolders.
    If ``AGENT_PLUGIN_DIRS`` is set (comma-separated), only those paths are used (must exist).
    Otherwise: shipped ``app/plugins`` tree, then ``AGENT_PLUGINS_EXTRA_DIR`` if set.
    Earlier roots / lexicographically earlier paths win when two files define the same tool name.
    """
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            r = p.resolve()
        except OSError:
            logger.warning("plugin directory not resolvable: %s", p)
            return
        if not r.is_dir():
            return
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)

    raw = (os.environ.get("AGENT_PLUGIN_DIRS") or "").strip()
    if raw:
        for part in raw.split(","):
            add(Path(part.strip()).expanduser())
        return out
    import app as ap

    add(Path(ap.__path__[0]) / "plugins")
    if PLUGINS_EXTRA_DIR:
        add(Path(PLUGINS_EXTRA_DIR).expanduser())
    return out


# Comma-separated SHA256 hex digests (64 chars). If set, each extra *.py must match one entry.
# Read on each extra-plugin scan (reload) so container env updates take effect without code change.
# Multi-tenant HTTP: stable user id per request (comma-separated header names; first non-empty wins).
# Default fits Open WebUI with ENABLE_FORWARD_USER_INFO_HEADERS=true (X-OpenWebUI-User-Id).
# Without AGENT_API_KEY, clients can spoof headers.
def _user_sub_headers() -> list[str]:
    raw = (os.environ.get("AGENT_USER_SUB_HEADER") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return ["X-OpenWebUI-User-Id", "X-Agent-User-Sub"]


USER_SUB_HEADERS = _user_sub_headers()
TENANT_ID_HEADER = (
    os.environ.get("AGENT_TENANT_ID_HEADER") or "X-Agent-Tenant-Id"
).strip()
DEFAULT_EXTERNAL_SUB = (
    os.environ.get("AGENT_DEFAULT_EXTERNAL_SUB") or "default"
).strip() or "default"

# Fernet URL-safe base64 key for encrypting user_secrets at rest (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
SECRETS_MASTER_KEY = (os.environ.get("AGENT_SECRETS_MASTER_KEY") or "").strip()

# Optional base URL for curl examples in register_secrets / secrets_help (e.g. https://agent.example.com). Else 127.0.0.1:AGENT_HTTP_PORT.
PUBLIC_BASE_URL = (os.environ.get("AGENT_PUBLIC_URL") or "").strip().rstrip("/")
HTTP_EXAMPLE_PORT = (os.environ.get("AGENT_HTTP_PORT") or "8088").strip() or "8088"

# Local files plugin (workspace_*): set to an absolute path inside the container and mount it (compose volume).
WORKSPACE_ROOT = (os.environ.get("AGENT_WORKSPACE_ROOT") or "").strip()
WORKSPACE_MAX_FILE_BYTES = _env_int("AGENT_WORKSPACE_MAX_FILE_BYTES", 1_200_000)
WORKSPACE_MAX_LIST_ENTRIES = _env_int("AGENT_WORKSPACE_MAX_LIST_ENTRIES", 500)
WORKSPACE_MAX_SEARCH_FILES = _env_int("AGENT_WORKSPACE_MAX_SEARCH_FILES", 2000)
WORKSPACE_MAX_SEARCH_MATCHES = _env_int("AGENT_WORKSPACE_MAX_SEARCH_MATCHES", 100)
WORKSPACE_SEARCH_MAX_FILE_BYTES = _env_int("AGENT_WORKSPACE_SEARCH_MAX_FILE_BYTES", 400_000)
WORKSPACE_MAX_GLOB_FILES = _env_int("AGENT_WORKSPACE_MAX_GLOB_FILES", 2000)
WORKSPACE_MAX_READ_LINES = _env_int("AGENT_WORKSPACE_MAX_READ_LINES", 8000)

# create_tool limits / codegen (CREATE_TOOL_ENABLED is set above with PLUGINS_EXTRA_DIR).
CREATE_TOOL_MAX_BYTES = _env_int("AGENT_CREATE_TOOL_MAX_BYTES", 120_000)
# When create_tool is called without ``source``, Ollama generates the module (same base URL as chat).
CREATE_TOOL_CODEGEN_MODEL = (
    os.environ.get("AGENT_CREATE_TOOL_CODEGEN_MODEL") or "qwen2.5-coder:3b"
).strip()
CREATE_TOOL_CODEGEN_TIMEOUT = _env_int("AGENT_CREATE_TOOL_CODEGEN_TIMEOUT", 120)
# Codegen prompt: allow httpx/urllib HTTP (keys only via os.environ — set in compose .env).
CREATE_TOOL_CODEGEN_ALLOW_NETWORK = _env_bool("AGENT_CREATE_TOOL_CODEGEN_ALLOW_NETWORK", False)
# Codegen: max Ollama attempts (validate + write + reload + test_tool probe). 1 = no retry; cap 20.
CREATE_TOOL_CODEGEN_MAX_ATTEMPTS = max(
    1, min(_env_int("AGENT_CREATE_TOOL_CODEGEN_MAX_ATTEMPTS", 1), 20)
)


def tool_log_redact_keys() -> frozenset[str]:
    """Argument names to redact in tool_invocations logging (comma-separated env)."""
    raw = (os.environ.get("AGENT_TOOL_LOG_REDACT_KEYS") or "source").strip()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def plugins_allowed_sha256() -> frozenset[str] | None:
    raw = os.environ.get("AGENT_PLUGINS_ALLOWED_SHA256", "").strip()
    if not raw:
        return None
    digests = frozenset(p.strip().lower() for p in raw.split(",") if p.strip())
    return digests if digests else None
