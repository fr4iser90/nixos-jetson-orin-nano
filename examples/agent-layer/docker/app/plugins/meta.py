"""Meta-tools: list all registered tools and show help for one tool."""

from __future__ import annotations

import json
from typing import Any, Callable

from .. import config
from .. import db
from .. import identity
from .. import secret_otp_bundle
from ..registry import get_registry

__version__ = "1.5.2"
PLUGIN_ID = "meta"


def list_available_tools(arguments: dict[str, Any]) -> str:
    """Return every tool name, description, and JSON Schema parameters (as registered)."""
    _ = arguments
    reg = get_registry()
    tools_out: list[dict[str, Any]] = []
    for spec in reg.openai_tools:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        tools_out.append(
            {
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
            }
        )
    return json.dumps(
        {
            "ok": True,
            "count": len(tools_out),
            "tools": tools_out,
            "hint": "Use get_tool_help with a tool name for one schema in full, or call a tool with JSON args per parameters.properties / required.",
        },
        ensure_ascii=False,
    )


def get_tool_help(arguments: dict[str, Any]) -> str:
    """Return full description + parameter schema for a single tool."""
    name = (arguments.get("tool_name") or "").strip()
    if not name:
        return json.dumps({"ok": False, "error": "tool_name is required"})
    reg = get_registry()
    for spec in reg.openai_tools:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        if fn.get("name") != name:
            continue
        return json.dumps(
            {
                "ok": True,
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
                "how_to_use": (
                    "The model calls this tool with a JSON object matching "
                    "`parameters.properties`; required keys are in `parameters.required`."
                ),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": False,
            "error": f"unknown tool: {name}",
            "hint": "Call list_available_tools for valid names.",
        },
        ensure_ascii=False,
    )


def register_secrets(arguments: dict[str, Any]) -> str:
    """
    Mint a one-time code bound to the current chat user; return a bash-safe curl that only needs
    the secret placeholder replaced (no Bearer / user headers for the end user).
    """
    if not config.SECRETS_MASTER_KEY:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "Speichern ist auf dem Server nicht aktiviert: Betreiber muss einmalig "
                    "AGENT_SECRETS_MASTER_KEY in docker/.env setzen (Verschlüsselung in Postgres — "
                    "Endnutzer tragen das nie ein). Siehe TOOLS.md."
                ),
            },
            ensure_ascii=False,
        )
    raw_svc = secret_otp_bundle.normalize_service_key(
        arguments.get("service_key_example")
    )
    ttl = secret_otp_bundle.ttl_clamp(arguments.get("ttl_seconds"))
    payload = secret_otp_bundle.build_otp_curl_payload(raw_svc, ttl)
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def secrets_help(arguments: dict[str, Any]) -> str:
    """Static help for user secrets: OTP only via register_secrets; no OTP is minted here."""
    raw_svc = secret_otp_bundle.normalize_service_key(
        arguments.get("service_key_example")
    )
    topic = (arguments.get("topic") or "").strip().lower()

    base = config.PUBLIC_BASE_URL or f"http://127.0.0.1:{config.HTTP_EXAMPLE_PORT}"
    user_hdr = (
        config.USER_SUB_HEADERS[0] if config.USER_SUB_HEADERS else "X-OpenWebUI-User-Id"
    )

    _tid, uid = identity.get_identity()
    resolved_sub = db.user_external_sub(uid)
    user_value = resolved_sub if resolved_sub is not None else "DEINE_WEBUI_USER_ID"

    hints: list[str] = [
        "Neues Secret speichern: **nur** Tool `register_secrets` — in der Antwort stehen `curl_bash` und ggf. `jq_register_example_de` (OTP ist schon eingebaut).",
        "Dieses Tool (`secrets_help`) erzeugt **kein** OTP und keinen curl — nur Erklärung.",
        "Gespeicherte `service_key`-Namen auflisten oder einen Key löschen: HTTP `GET`/`DELETE` `/v1/user/secrets` mit denselben User-Headern wie der Chat (optional Bearer `AGENT_API_KEY`) — siehe TOOLS.md.",
    ]
    if topic in ("email", "imap", "mail", "gmail"):
        hints.append(
            "Gmail: Google-Konto → App-Passwort; `service_key` z. B. `gmail` oder `email_imap`."
        )
    if topic in ("github", "gh", "pat"):
        hints.append(
            'GitHub: `service_key` `github_pat` — JSON `{"token":"…"}` oder Operator setzt `GITHUB_TOKEN` in docker/.env für alle Nutzer.'
        )
    if topic in ("calendar", "ics", "caldav", "nextcloud"):
        hints.append(
            'Kalender read-only: `calendar_ics` oder `google_calendar` mit JSON `{"ics_url":"https://…"}` — '
            "Google: Einstellungen → geheime iCal-Adresse (`calendar.google.com/.../basic.ics`)."
        )
    if topic in ("google", "gcal", "google_calendar"):
        hints.append(
            'Google Kalender: `register_secrets` mit `service_key_example: "google_calendar"`; Secret = iCal-URL aus den Google-Kalendereinstellungen.'
        )

    return json.dumps(
        {
            "ok": True,
            "otp_only_from_register_secrets_de": (
                "Ein **OTP** und der fertige **`curl_bash`** kommen **ausschließlich** aus der Tool-Antwort von "
                "`register_secrets`. **`secrets_help` ruft das Backend nicht an** und erzeugt **kein** OTP."
            ),
            "when_backend_emits_otp_de": (
                "Wenn dein Modell keine `tool_calls` sendet (Log z. B. „no tool_calls and content fallback missed“), "
                "wird `register_secrets` nicht ausgeführt → **kein** OTP. Dann größeres Modell mit Tool-Calling nutzen oder "
                "`AGENT_CONTENT_TOOL_FALLBACK`/Prompt anpassen."
            ),
            "gmail_save_use_this_tool": "register_secrets",
            "gmail_save_example_args": {"service_key_example": "gmail"},
            "google_calendar_save_example_args": {
                "service_key_example": "google_calendar"
            },
            "service_key_example": raw_svc,
            "base_url_used": base,
            "user_header": user_hdr,
            "resolved_user_id": uid,
            "resolved_external_sub": user_value,
            "for_llm_de": (
                "Neues Secret speichern: **nur** `register_secrets` mit passendem `service_key_example` "
                "(gmail, google_calendar, github_pat, …). Dem Nutzer **nur** `curl_bash` / `jq_register_example_de` "
                "aus **dieser** Antwort geben — nichts erfinden. Klartext-Secrets und iCal-URLs **nie** in den Chat."
            ),
            "common_mistakes_de": [
                "Falsch: `secrets_help` aufrufen und erwarten, dass ein OTP oder curl erscheint.",
                "Falsch: Geheime iCal-URL oder Passwörter in den Chat schreiben — nur lokal im Terminal im curl/jq.",
            ],
            "preferred_flow_de": (
                "`register_secrets` → Nutzer führt `curl_bash` (eine Zeile) lokal aus → HTTP-Antwort `stored:true`. "
                "Danach z. B. `calendar_ics_list_events` für Google-Kalender."
            ),
            "steps_de": [
                "Tool `register_secrets` mit JSON-Argumenten aufrufen, z. B. "
                '`{"service_key_example":"google_calendar"}` oder `{"service_key_example":"gmail"}`.',
                "Aus der **Tool-Antwort** `curl_bash` oder `jq_register_example_de` kopieren, Platzhalter lokal ersetzen, ausführen.",
                "Bei Google-Kalender: in `secret` die komplette https-URL (`…/basic.ics`) einsetzen (nur im Terminal).",
            ],
            "list_delete_note_de": (
                "Gespeicherte Keys auflisten oder löschen: REST `GET` bzw. `DELETE /v1/user/secrets` "
                "mit User-Header wie beim Chat; bei gesetztem `AGENT_API_KEY` Header "
                "`Authorization: Bearer <AGENT_API_KEY>`. Details: TOOLS.md."
            ),
            "hints": hints,
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "list_available_tools": list_available_tools,
    "get_tool_help": get_tool_help,
    "register_secrets": register_secrets,
    "secrets_help": secrets_help,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_available_tools",
            "description": (
                "Lists all tools this agent can run: name, short description, and JSON parameter schema. "
                "Use when the user asks what you can do, which tools exist, or how to get started."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tool_help",
            "description": (
                "Returns full help for one tool: description and parameter schema. "
                "Use when the user asks how to use a specific tool by name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Exact tool name, e.g. create_todo, search_web",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_secrets",
            "description": (
                "ONLY way to get a valid OTP and curl for saving a user secret. You MUST invoke this tool — "
                "NEVER invent or type a curl command yourself (wrong OTP, wrong JSON, broken quotes). "
                "Copy to the user ONLY the exact curl_bash string from YOUR tool response JSON (and jq_register_example_de if present). "
                "Match service_key_example to what the user asked for: Google Calendar iCal URL → google_calendar; Gmail → gmail; GitHub PAT → github_pat; generic ICS → calendar_ics. "
                "Always include for_assistant_must_say_de: secret is NOT stored until the user runs that curl/jq and gets stored:true. "
                "Do NOT pretty-print curl_bash. Never paste real secrets or iCal URLs into chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_key_example": {
                        "type": "string",
                        "description": (
                            "Must match the integration: google_calendar (Google secret iCal link), calendar_ics (other HTTPS ICS), "
                            "gmail (IMAP app password JSON), github_pat (token JSON). Lowercase [a-z0-9._-]."
                        ),
                    },
                    "ttl_seconds": {
                        "type": "integer",
                        "description": "Optional OTP lifetime 120–3600 (default 600).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "secrets_help",
            "description": (
                "Static help for user secrets: explains that OTP and curl_bash come ONLY from register_secrets — "
                "this tool does NOT mint an OTP. To save Gmail, google_calendar, github_pat, etc., the model must "
                "call register_secrets and pass the returned curl_bash to the user. "
                "Returns steps_de, google_calendar_save_example_args, list_delete_note_de (REST for list/delete), hints."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_key_example": {
                        "type": "string",
                        "description": (
                            "Example service_key name for hints only (lowercase [a-z0-9._-]), "
                            "e.g. gmail, google_calendar, github_pat"
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "description": (
                            "Optional hint: email, imap, mail, gmail, github, google, gcal, calendar, ics, or generic"
                        ),
                    },
                },
            },
        },
    },
]
