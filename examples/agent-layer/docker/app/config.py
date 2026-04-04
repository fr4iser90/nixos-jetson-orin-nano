import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def tools_backup_directory() -> Path:
    raw = (os.environ.get("AGENT_TOOLS_BACKUP_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(DATA_DIR) / "tool_backups"


def normalize_tool_mode(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s == "default":
        return "default_chat"
    if s in ("full", "tool_factory", "workspace", "default_chat"):
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
# Before replace_tool / update_tool / create_tool overwrite, copy prior .py here (UTC timestamp prefix).
TOOLS_BACKUP_ENABLED = _env_bool("AGENT_TOOLS_BACKUP_ENABLED", True)
OPTIONAL_API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
SYSTEM_PROMPT_EXTRA = os.environ.get("AGENT_SYSTEM_PROMPT", "").strip()

# If Ollama returns no tool_calls but JSON tool intent in message content (e.g. Nemotron), parse and run.
CONTENT_TOOL_FALLBACK = _env_bool("AGENT_CONTENT_TOOL_FALLBACK", True)

# Per Ollama round: INFO log reply type (TOOLS vs TEXT), context size, optional assistant preview (redacted).
AGENT_LOG_LLM_ROUNDS = _env_bool("AGENT_LOG_LLM_ROUNDS", True)
AGENT_LOG_ASSISTANT_PREVIEW_CHARS = _env_int("AGENT_LOG_ASSISTANT_PREVIEW_CHARS", 0)
AGENT_LOG_LARGE_CONTEXT_CHARS = _env_int("AGENT_LOG_LARGE_CONTEXT_CHARS", 120_000)

# --- Tool routing (subset by mode; header X-Agent-Mode overrides) ---
# full | tool_factory | workspace | default_chat (alias: default)
AGENT_TOOL_MODE = normalize_tool_mode(os.environ.get("AGENT_TOOL_MODE", "full"))

AGENT_TOOL_MODE_TOOL_FACTORY_INCLUDES_HELP = _env_bool(
    "AGENT_TOOL_MODE_TOOL_FACTORY_INCLUDES_HELP", True
)
# When true: ``filter_tools_for_mode`` applies tool_factory / workspace / default_chat subsets (see ``tool_routing._filter_tools_subset_by_mode``). Default off = all tools to the LLM.
AGENT_TOOL_SUBSET_BY_MODE = _env_bool("AGENT_TOOL_SUBSET_BY_MODE", False)
# If no X-Agent-Mode / JSON agent_tool_mode: keyword substring match on last user message
AGENT_TOOL_ROUTER_KEYWORDS_ENABLED = _env_bool("AGENT_TOOL_ROUTER_KEYWORDS_ENABLED", True)
# Comma-separated case-insensitive substrings (empty = use built-in defaults in agent)
AGENT_TOOL_ROUTER_KEYWORDS_TOOL_FACTORY = os.environ.get(
    "AGENT_TOOL_ROUTER_KEYWORDS_TOOL_FACTORY", ""
).strip()
AGENT_TOOL_ROUTER_KEYWORDS_WORKSPACE = os.environ.get(
    "AGENT_TOOL_ROUTER_KEYWORDS_WORKSPACE", ""
).strip()
# Optional second stage: one short Ollama call when keywords are inconclusive
AGENT_TOOL_ROUTER_LLM_ENABLED = _env_bool("AGENT_TOOL_ROUTER_LLM_ENABLED", False)
AGENT_TOOL_ROUTER_MODEL = (os.environ.get("AGENT_TOOL_ROUTER_MODEL") or "").strip()
# After workspace_* fails with "disabled", narrow remaining rounds to tool_factory tools
AGENT_TOOL_RETRY_NARROW_TO_TOOL_FACTORY = _env_bool(
    "AGENT_TOOL_RETRY_NARROW_TO_TOOL_FACTORY", True
)
# After a tool returns text that looks like an HTTP client/API error, inject a short system hint
# so the model can read_tool / search_web / replace_tool without the user (see TOOLS.md).
AGENT_TOOL_HTTP_ERROR_RECOVERY_HINTS = _env_bool(
    "AGENT_TOOL_HTTP_ERROR_RECOVERY_HINTS", True
)

# In tool_factory mode: if chat ``model`` id contains any substring (case-insensitive), drop listed tools.
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

# Extra tool tree (optional): scan + create_tool writes here. Two different concerns:
# - ENABLE = whether create_tool may run (security / ops).
# - DIR = filesystem path (must exist in the container; Docker still needs a volume mount for a host folder).
# If ENABLE is true and AGENT_TOOLS_EXTRA_DIR is unset/empty, default /data/tools (typical compose mount target).
CREATE_TOOL_ENABLED = _env_bool("AGENT_CREATE_TOOL_ENABLED", False)
_TOOLS_EXTRA_RAW = (os.environ.get("AGENT_TOOLS_EXTRA_DIR") or "").strip()
TOOLS_EXTRA_DIR = _TOOLS_EXTRA_RAW or ("/data/tools" if CREATE_TOOL_ENABLED else "")


def tool_scan_directories() -> list[Path]:
    """
    Tool **roots** to scan **recursively** for ``*.py`` (TOOLS + HANDLERS), including subfolders.
    If ``AGENT_TOOL_DIRS`` is set (comma-separated), only those paths are used (must exist).
    Otherwise: shipped ``agent_tools`` tree (sibling of the ``app`` package), then ``AGENT_TOOLS_EXTRA_DIR`` if set.
    Earlier roots / lexicographically earlier paths win when two files define the same tool name.
    """
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            r = p.resolve()
        except OSError:
            logger.warning("tool directory not resolvable: %s", p)
            return
        if not r.is_dir():
            return
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)

    raw = (os.environ.get("AGENT_TOOL_DIRS") or "").strip()
    if raw:
        for part in raw.split(","):
            add(Path(part.strip()).expanduser())
        return out

    # Repo layout: examples/agent-layer/docker/{app,agent_tools}; image WORKDIR /app.
    add(Path(__file__).resolve().parent.parent / "agent_tools")
    if TOOLS_EXTRA_DIR:
        add(Path(TOOLS_EXTRA_DIR).expanduser())
    return out


# Comma-separated SHA256 hex digests (64 chars). If set, each extra *.py must match one entry.
# Read on each extra-tool scan (reload) so container env updates take effect without code change.
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

# Local files tool (workspace_*): set to an absolute path inside the container and mount it (compose volume).
WORKSPACE_ROOT = (os.environ.get("AGENT_WORKSPACE_ROOT") or "").strip()
WORKSPACE_MAX_FILE_BYTES = _env_int("AGENT_WORKSPACE_MAX_FILE_BYTES", 1_200_000)
WORKSPACE_MAX_LIST_ENTRIES = _env_int("AGENT_WORKSPACE_MAX_LIST_ENTRIES", 500)
WORKSPACE_MAX_SEARCH_FILES = _env_int("AGENT_WORKSPACE_MAX_SEARCH_FILES", 2000)
WORKSPACE_MAX_SEARCH_MATCHES = _env_int("AGENT_WORKSPACE_MAX_SEARCH_MATCHES", 100)
WORKSPACE_SEARCH_MAX_FILE_BYTES = _env_int("AGENT_WORKSPACE_SEARCH_MAX_FILE_BYTES", 400_000)
WORKSPACE_MAX_GLOB_FILES = _env_int("AGENT_WORKSPACE_MAX_GLOB_FILES", 2000)
WORKSPACE_MAX_READ_LINES = _env_int("AGENT_WORKSPACE_MAX_READ_LINES", 8000)

# create_tool limits / codegen (CREATE_TOOL_ENABLED is set above with TOOLS_EXTRA_DIR).
CREATE_TOOL_MAX_BYTES = _env_int("AGENT_CREATE_TOOL_MAX_BYTES", 120_000)
# When create_tool is called without ``source``, Ollama generates the module (same base URL as chat).
CREATE_TOOL_CODEGEN_MODEL = (
    os.environ.get("AGENT_CREATE_TOOL_CODEGEN_MODEL") or "qwen2.5-coder:7b"
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


def tools_allowed_sha256() -> frozenset[str] | None:
    raw = os.environ.get("AGENT_TOOLS_ALLOWED_SHA256", "").strip()
    if not raw:
        return None
    digests = frozenset(p.strip().lower() for p in raw.split(",") if p.strip())
    return digests if digests else None
