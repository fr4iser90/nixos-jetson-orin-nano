# Agent layer — Tools

Übersicht über **eingebaute** und **geplante** Tools, dazu Ideen für Erweiterungen.  
Implementierung: jeweils Plugin-Modul mit `TOOLS` (OpenAI-Schema) + `HANDLERS` (Python). Secrets über **Umgebungsvariablen** / **`.env`** (siehe `docker/.env.example`), nicht hardcoden.

---

## Checkliste (built-in)

| Status | Tool | Plugin | Kurzbeschreibung |
|--------|------|--------|------------------|
| [x] | `get_current_time` | `clock` | IANA-Zeitzone, ISO-Zeit (ohne DB). |
| [x] | `create_todo` | `todos` | Todo in Postgres anlegen. |
| [x] | `list_todos` | `todos` | Todos listen (max. 100). |
| [x] | `set_todo_status` | `todos` | Status `open` / `done` / `cancelled`. |
| [x] | `search_web` | `web_search` | Tavily → Brave → **ddgs**-Metasuche ohne API-Key (inoffiziell). |
| [x] | `deep_search` | `web_search` | Tavily: `raw_content`. Ohne: Snippets + **Seitenabruf** wenn `robots.txt` den UA erlaubt (`fetch_status`, `raw_content`). Abschalten: `AGENT_DISABLE_FETCH_DEEP=true`. |
| [x] | `list_available_tools` | `meta` | Alle Tools mit Beschreibung + JSON-Schema (Parameter). |
| [x] | `get_tool_help` | `meta` | Hilfe zu einem Tool nach Namen (`tool_name`). |

**Hilfe / „Welche Tools gibt es?“**

- Pro Tool: **`description`** + **`parameters`** im OpenAI-Schema (sieht das Modell in jedem Request).
- Explizit abfragbar: **`list_available_tools`** (Übersicht), **`get_tool_help`** mit `tool_name` (ein Tool ausführlich + kurzer `how_to_use`-Hinweis).

**Validiert (manuell / Stack):** Tool-Loop über Agent → Ollama, Einträge in `todos` + `tool_invocations`; Open WebUI mit OpenAI-Base-URL auf den Agent; `stream: true` über SSE-Shim; Tool-Merge mit WebUI-`tools`; Content-JSON-Fallback für Modelle mit `reasoning`-Feld.

---

## Checkliste (geplant / optional)

| Status | Tool / Paket | Hinweis |
|--------|----------------|---------|
| [ ] | GitHub Search / Repo-Read | Fine-grained PAT, nur nötige Scopes. |
| [x] | HTTP-Fetch + robots.txt + noindex | `deep_search` ohne Tavily; optionale Allowlist via Env. |
| [ ] | Weitere Search-Provider (SerpAPI, …) | Optional ergänzen. |
| [ ] | Lokale Dateien (read-only Mount) | Nur definierte Pfade. |
| [ ] | Home Assistant / MQTT | Topic-Whitelist. |
| [ ] | RAG / `search_kb` | pgvector, Chroma, … |

*(Status hier anpassen, sobald ein Plugin gemerged und einmal gegen euren Stack getestet ist.)*

---

## API-Keys & `.env`

Empfehlung: **eine** `docker/.env` (von `.env.example` kopieren), **nicht** committen.

- **Heute:** meist nur Postgres/Ollama/Agent-Settings (`DATABASE_URL`, `OLLAMA_BASE_URL`, `AGENT_API_KEY`, …).
- **Web-Suche:** optional `TAVILY_API_KEY` / `BRAVE_SEARCH_API_KEY`; ohne Keys nutzt das Plugin **[ddgs](https://pypi.org/project/ddgs/)** (Metasuche, u. a. Bing/DuckDuckGo-Backends; ohne Vertrag, Rate-Limits möglich). Abschalten: `AGENT_DISABLE_DDG_SEARCH=true`. Zusätzlich `AGENT_SEARCH_TIMEOUT`, `AGENT_SEARCH_MAX_RAW_CHARS`.
- **deep_search ohne Tavily:** pro Treffer optional **HTTP-GET** der URL, nur wenn `robots.txt` für `AGENT_FETCH_USER_AGENT` (Default: `JetpackAgentLayer/…`) **kein** `Disallow` setzt; sonst `fetch_status=robots_disallowed`, kein Abruf. **`AGENT_ROBOTS_STRICT=true`:** wenn `robots.txt` nicht lesbar ist, wird **nicht** gefetcht (Default: in dem Fall wie „keine Regeln“ behandelt). **`AGENT_DISABLE_FETCH_DEEP=true`:** nur Snippets. **`AGENT_FETCH_MAX_BYTES`:** max. Antwortgröße (Default 2 MB). **`AGENT_ROBOTS_CACHE_TTL`:** Cache für `robots.txt` pro Origin (Sekunden). Loopback/Link-Local/Metadata-Hosts werden nicht abgerufen (Basis-SSRF-Schutz). **`AGENT_RESPECT_META_ROBOTS`** (Default `true`): bei **`X-Robots-Tag`** oder **`<meta name="robots" content="…">`** mit **`noindex`** oder **`none`** wird **kein** `raw_content` geliefert (`fetch_status` z. B. `x_robots_noindex` / `meta_robots_noindex`). **`AGENT_FETCH_DOMAIN_ALLOWLIST`:** wenn gesetzt (kommagetrennte Hostnamen), nur noch diese Hosts und ihre Subdomains — alles andere `blocked_allowlist` (reduziert SSRF + Scope).
- **Später (Beispiele):** `GITHUB_TOKEN=…`, `SERPAPI_API_KEY=…` — im jeweiligen Plugin aus `os.environ` lesen.

Für Produktion alternativ **NixOS sops-nix** / Secrets-Store statt flacher `.env`.

---

## Kategorien (Ideenkatalog)

### Web / Research

| Ansatz | Bemerkung |
|--------|-----------|
| Search-API (Brave, Tavily, SerpAPI, Google CSE) | Stabil, ToS/Quota beachten. |
| URL-Fetch | Nur mit **Allowlist**; sonst SSRF. |
| Reader-APIs (Firecrawl, Jina, …) | Oft kostenpflichtig; Inhalte gekürzt liefern. |

### GitHub

- `search/code`, `search/repositories`, `search/issues` über REST API.  
- PAT minimal halten (read-only wo möglich).

### System / Homelab

- **Shell:** nur Allowlist einzelner Befehle oder RPC auf Host.  
- **Monitoring:** Prometheus-Query, interne Health-URLs.  
- **Container:** nur mit klar eingeschränkter API — nie blind Socket mounten.

### Bereits woanders im Repo

- Whisper / faster-whisper / ComfyUI als **eigene** Services; der Agent kann sie per HTTP-Tool ansprechen, falls du ein Plugin dafür schreibst.

---

## Plugin-Vertrag (Kurz)

```text
TOOLS: list[dict]          # OpenAI function specs
HANDLERS: dict[str, callable]  # name -> fn(args: dict) -> str (JSON-String)
PLUGIN_ID: str             # optional
__version__: str           # optional
```

Reload Built-in + Extra: `POST /v1/admin/reload-plugins?scope=all|extra`.

---

## Sicherheit (Merksatz)

Jedes Tool ist **ausführbarer Code** mit den Rechten des Agent-Containers. Lieber zu wenige, gut begrenzte Tools als ein generisches „run_shell“.
