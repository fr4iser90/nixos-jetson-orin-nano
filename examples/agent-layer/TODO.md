ERROR 500 OLLAMA 

Was passiert hier konkret
Agent layer sammelt Tools → 36 Tools in deinem Log.
Agent schätzt die Tokens (est_tokens~4445-5926) und packt alles in die JSON-Payload.
HTTP POST an Ollama → Ollama crasht (500 Internal Server Error) mit XML-Syntax-Fehler:
"XML syntax error on line 5: element <function> closed by </parameter>"

Das bedeutet: Ollama versucht intern, die Tool-Payload zu parsen, und die JSON → XML Konvertierung oder das interne Schema passt nicht. Ist also Ollama Bug oder Limit, kein Fehler im Agent-Layer.

Strategien, wie du den Agent-Layer stabiler machst
Retry / Stream-Mechanismus
Agent kann auf 500 reagieren und die Anfrage wiederholen (z. B. max 3 Versuche, exponential backoff).
Alternative: Bei Streaming-Mode (/v1/chat/completions?stream=true) kann der Layer versuchen, den Stream erneut zu öffnen, falls er mittendrin crasht.
Chunking / Reduktion der Payload
36 Tools + geschätzte 4.5–5.9k Tokens → Ollama crasht evtl. wegen zu großer JSON.
Lösung: nur die Tools senden, die für diese Runde nötig sind, oder Tools in mehrere Calls splitten.
Fallback-Logik
Layer kann Tool-Call auf lokale Mock/Cache-Version umleiten, wenn Ollama 500 zurückgibt, sodass Nutzer nicht hängen bleibt.
Error Handling für Tool Calls
Aktuell crasht die ganze Chat-Completion, wenn ein Tool 500 gibt.
Besser: Tool fehlschlagen lassen → JSON mit "ok": False, "error": "ollama 500" → LLM bekommt Text, keine Exception.