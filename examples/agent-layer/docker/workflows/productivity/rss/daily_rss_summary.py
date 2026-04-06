
Cron (z.B. alle 6h)
    ↓
Dein Python Agent
    ↓
Für jede RSS-Quelle:
    ├─→ Neues LLM-Instance (oder explizit Context leeren)
    ├─→ Hole Artikel
    ├─→ Für jeden Artikel: Zusammenfassung
    ├─→ Speichere Ergebnis (JSON/DB)
    └─→ Context löschen / Neues Model laden
    ↓
Gesammelte Zusammenfassungen → Irgendwo hin (E-Mail, Webhook, Open WebUI)