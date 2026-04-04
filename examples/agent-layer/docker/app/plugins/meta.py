"""Meta-tools: list all registered tools and show help for one tool."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any, Callable

from .. import config
from .. import db
from .. import identity
from ..registry import get_registry

__version__ = "1.5.0"
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


_SERVICE_KEY_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


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
    raw_svc = (arguments.get("service_key_example") or "email_imap").strip().lower()
    if not _SERVICE_KEY_SAFE.fullmatch(raw_svc):
        raw_svc = "email_imap"
    ttl = 600
    raw_ttl = arguments.get("ttl_seconds")
    if isinstance(raw_ttl, (int, float)):
        t = int(raw_ttl)
        if 120 <= t <= 3600:
            ttl = t

    _tid, uid = identity.get_identity()
    otp = db.secret_upload_otp_create(uid, ttl_seconds=ttl)
    base = config.PUBLIC_BASE_URL or f"http://127.0.0.1:{config.HTTP_EXAMPLE_PORT}"
    if raw_svc == "gmail":
        secret_blob = '{"email":"du@gmail.com","app_password":"DEIN_APP_PASSWORT"}'
    elif raw_svc == "github_pat":
        secret_blob = '{"token":"DEIN_GITHUB_PAT_ODER_github_pat_xxx"}'
    elif raw_svc == "calendar_ics":
        secret_blob = '{"ics_url":"https://DEINE_CLOUD/.../calendar.ics"}'
    elif raw_svc == "google_calendar":
        secret_blob = (
            '{"ics_url":"https://calendar.google.com/calendar/ical/DEINE_MAIL%40gmail.com/'
            'private-XXXX/basic.ics"}'
        )
    else:
        secret_blob = "DEIN_SECRET_TEXT"
    body_str = json.dumps(
        {"otp": otp, "service_key": raw_svc, "secret": secret_blob},
        ensure_ascii=False,
    )
    url = f"{base}/v1/user/secrets/register-with-otp"
    curl_bash = (
        f"curl -sS -X POST {shlex.quote(url)} "
        f"-H {shlex.quote('Content-Type: application/json')} "
        f"--data-raw {shlex.quote(body_str)}"
    )

    jq_hint: str | None = None
    if raw_svc == "gmail":
        jq_hint = (
            "Eine Zeile: in --arg e und --arg p nur DEINE@gmail.com und DEIN_APP_PASSWORT ersetzen (OTP schon gesetzt).\n"
            "curl -sS -X POST "
            + shlex.quote(url)
            + " -H 'Content-Type: application/json' "
            + '-d "$(jq -nc --arg o '
            + shlex.quote(otp)
            + " --arg sk gmail --arg e 'DEINE@gmail.com' --arg p 'DEIN_APP_PASSWORT' "
            + "'{otp:$o, service_key:$sk, secret: ({email:$e, app_password:$p} | tojson)}')\""
        )
    elif raw_svc == "github_pat":
        jq_hint = (
            "Eine Zeile: --arg t = Fine-grained PAT oder klassisch ghp_… (OTP schon in --arg o).\n"
            "curl -sS -X POST "
            + shlex.quote(url)
            + " -H 'Content-Type: application/json' "
            + '-d "$(jq -nc --arg o '
            + shlex.quote(otp)
            + " --arg sk github_pat --arg t 'DEIN_GITHUB_PAT' "
            + "'{otp:$o, service_key:$sk, secret: ({token:$t} | tojson)}')\""
        )
    elif raw_svc == "calendar_ics":
        jq_hint = (
            "Eine Zeile: --arg u = HTTPS-ICS-URL (Nextcloud Export-Link o. ä.; OTP in --arg o).\n"
            "curl -sS -X POST "
            + shlex.quote(url)
            + " -H 'Content-Type: application/json' "
            + '-d "$(jq -nc --arg o '
            + shlex.quote(otp)
            + " --arg sk calendar_ics --arg u 'https://DEINE_CLOUD/.../export' "
            + "'{otp:$o, service_key:$sk, secret: ({ics_url:$u} | tojson)}')\""
        )
    elif raw_svc == "google_calendar":
        jq_hint = (
            "Google: In calendar.google.com → Einstellungen → Kalender → „Geheime Adresse im iCal-Format“ kopieren; "
            "in --arg u **eine Zeile** einfügen (OTP in --arg o).\n"
            "curl -sS -X POST "
            + shlex.quote(url)
            + " -H 'Content-Type: application/json' "
            + '-d "$(jq -nc --arg o '
            + shlex.quote(otp)
            + " --arg sk google_calendar --arg u 'https://calendar.google.com/calendar/ical/.../basic.ics' "
            + "'{otp:$o, service_key:$sk, secret: ({ics_url:$u} | tojson)}')\""
        )

    out: dict[str, Any] = {
        "ok": True,
        "for_assistant_must_say_de": (
            "Wichtig für die Antwort an den Nutzer: Das Secret ist **noch nicht** gespeichert. "
            "Erst nach erfolgreichem `curl`/`jq` im Terminal (HTTP-Antwort enthält stored:true) existiert es in Postgres. "
            "Nicht formulieren wie „already registered“, „no further action“, „secret is stored“ — das wäre falsch."
        ),
        "expires_in_seconds": ttl,
        "service_key": raw_svc,
        "resolved_user_id": uid,
        "curl_bash": curl_bash,
        "steps_de": (
            [
                "Befehl `curl_bash` ist **eine Zeile** — nicht umbrechen; sonst bricht JSON.",
                "Oder **eine** jq-Zeile: `jq_register_example_de` — dort `--arg e` = E-Mail, `--arg p` = App-Passwort, OTP schon drin.",
                "Alternativ Platzhalter in `curl_bash` ersetzen (lokal — nie in den Chat).",
            ]
            if raw_svc == "gmail"
            else [
                "Befehl `curl_bash` ist **eine Zeile**; oder `jq_register_example_de` mit `--arg t` = GitHub PAT.",
                "Nur lokal ausführen; Token nie in den Chat.",
            ]
            if raw_svc == "github_pat"
            else [
                "Befehl `curl_bash` eine Zeile; oder `jq_register_example_de` mit `--arg u` = HTTPS-ICS-URL.",
                "ICS-URL von Nextcloud/Google „Secret address in iCal format“ o. ä.; kein localhost.",
            ]
            if raw_svc == "calendar_ics"
            else [
                "Google Kalender: „Geheime Adresse im iCal-Format“ aus den Kalendereinstellungen kopieren.",
                "Befehl `curl_bash` eine Zeile; oder `jq_register_example_de` mit `--arg u` = diese https-URL (nie in den Chat posten).",
            ]
            if raw_svc == "google_calendar"
            else [
                "Befehl `curl_bash` im Terminal einfügen und ausführen (eine Zeile).",
                "Vorher nur den `secret`-Wert im JSON durch den echten Token/Passwort-Text ersetzen (lokal — nie in den Chat).",
            ]
        ),
        "security_de": (
            "Das OTP steht im Chat und verknüpft den Upload mit deinem Account. Wer deinen Chat mitlesen kann, "
            "könnte es missbrauchen — Befehl zeitnah ausführen; OTP ist einmalig und läuft ab."
        ),
        "operator_note_de": (
            "AGENT_SECRETS_MASTER_KEY ist nur Server-Konfiguration (Fernet), kein Wert für Nutzer im Chat."
        ),
        "shell_gt_prompt_means_de": (
            "Wenn die Shell nur `>` anzeigt: ein Anführungszeichen ist noch offen — mit Ctrl+C abbrechen. "
            "Dann `curl_bash` als **eine** Zeile einfügen (aus dem Tool-JSON kopieren, nicht mehrzeilig umbrechen); "
            "bei gmail alternativ `jq_register_example_de`. Typischer Fehler: `}'`'' oder fehlendes schließendes `'`."
        ),
    }
    if jq_hint:
        out["jq_register_example_de"] = jq_hint

    return json.dumps(out, ensure_ascii=False)


def secrets_help(arguments: dict[str, Any]) -> str:
    """Static help for user secrets: OTP only via register_secrets; no OTP is minted here."""
    raw_svc = (arguments.get("service_key_example") or "email_imap").strip().lower()
    if not _SERVICE_KEY_SAFE.fullmatch(raw_svc):
        raw_svc = "email_imap"
    topic = (arguments.get("topic") or "").strip().lower()

    base = config.PUBLIC_BASE_URL or f"http://127.0.0.1:{config.HTTP_EXAMPLE_PORT}"
    user_hdr = config.USER_SUB_HEADERS[0] if config.USER_SUB_HEADERS else "X-OpenWebUI-User-Id"

    _tid, uid = identity.get_identity()
    resolved_sub = db.user_external_sub(uid)
    user_value = resolved_sub if resolved_sub is not None else "DEINE_WEBUI_USER_ID"

    hints: list[str] = [
        "Neues Secret speichern: **nur** Tool `register_secrets` — in der Antwort stehen `curl_bash` und ggf. `jq_register_example_de` (OTP ist schon eingebaut).",
        "Dieses Tool (`secrets_help`) erzeugt **kein** OTP und keinen curl — nur Erklärung.",
        "Gespeicherte `service_key`-Namen auflisten oder einen Key löschen: HTTP `GET`/`DELETE` `/v1/user/secrets` mit denselben User-Headern wie der Chat (optional Bearer `AGENT_API_KEY`) — siehe TOOLS.md.",
    ]
    if topic in ("email", "imap", "mail", "gmail"):
        hints.append("Gmail: Google-Konto → App-Passwort; `service_key` z. B. `gmail` oder `email_imap`.")
    if topic in ("github", "gh", "pat"):
        hints.append(
            "GitHub: `service_key` `github_pat` — JSON `{\"token\":\"…\"}` oder Operator setzt `GITHUB_TOKEN` in docker/.env für alle Nutzer."
        )
    if topic in ("calendar", "ics", "caldav", "nextcloud"):
        hints.append(
            "Kalender read-only: `calendar_ics` oder `google_calendar` mit JSON `{\"ics_url\":\"https://…\"}` — "
            "Google: Einstellungen → geheime iCal-Adresse (`calendar.google.com/.../basic.ics`)."
        )
    if topic in ("google", "gcal", "google_calendar"):
        hints.append(
            "Google Kalender: `register_secrets` mit `service_key_example: \"google_calendar\"`; Secret = iCal-URL aus den Google-Kalendereinstellungen."
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
            "google_calendar_save_example_args": {"service_key_example": "google_calendar"},
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
                "Register/store one user secret for CLI upload. Returns curl_bash (one line) and for gmail jq_register_example_de. "
                "Always include for_assistant_must_say_de in your reasoning: secret is NOT stored until the user runs curl/jq and gets stored:true. "
                "Do NOT pretty-print curl_bash to multiple lines. When repeating jq line, keep OTP quoted as in jq_register_example_de (shlex). "
                "Never paste real secrets into chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_key_example": {
                        "type": "string",
                        "description": (
                            "Logical name for this secret (lowercase [a-z0-9._-]), "
                            "e.g. gmail, github_pat, calendar_ics, google_calendar, email_imap"
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
