"""Shared OTP + curl_bash payload for register-with-otp (used by register_secrets tool and HTTP API)."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

from . import config
from . import db
from . import identity

_SERVICE_KEY_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


def normalize_service_key(raw: str | None, default: str = "email_imap") -> str:
    s = (raw or default).strip().lower()
    if not _SERVICE_KEY_SAFE.fullmatch(s):
        return default
    return s


def ttl_clamp(raw_ttl: Any, default: int = 600) -> int:
    if isinstance(raw_ttl, (int, float)):
        t = int(raw_ttl)
        if 120 <= t <= 3600:
            return t
    return default


def build_otp_curl_payload(service_key: str, ttl_seconds: int = 600) -> dict[str, Any]:
    """
    Mint OTP for current identity user; return the same fields as register_secrets (without top-level ok).
    Caller must ensure AGENT_SECRETS_MASTER_KEY is set.
    """
    raw_svc = normalize_service_key(service_key)
    ttl = ttl_seconds
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
            else (
                [
                    "Befehl `curl_bash` ist **eine Zeile**; oder `jq_register_example_de` mit `--arg t` = GitHub PAT.",
                    "Nur lokal ausführen; Token nie in den Chat.",
                ]
                if raw_svc == "github_pat"
                else (
                    [
                        "Befehl `curl_bash` eine Zeile; oder `jq_register_example_de` mit `--arg u` = HTTPS-ICS-URL.",
                        "ICS-URL von Nextcloud/Google „Secret address in iCal format“ o. ä.; kein localhost.",
                    ]
                    if raw_svc == "calendar_ics"
                    else (
                        [
                            "Google Kalender: „Geheime Adresse im iCal-Format“ aus den Kalendereinstellungen kopieren.",
                            "Befehl `curl_bash` eine Zeile; oder `jq_register_example_de` mit `--arg u` = diese https-URL (nie in den Chat posten).",
                        ]
                        if raw_svc == "google_calendar"
                        else [
                            "Befehl `curl_bash` im Terminal einfügen und ausführen (eine Zeile).",
                            "Vorher nur den `secret`-Wert im JSON durch den echten Token/Passwort-Text ersetzen (lokal — nie in den Chat).",
                        ]
                    )
                )
            )
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
    return out
