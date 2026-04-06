v1/tools korregieren
entweder alten copy paste für agent lassen
oder agent auch auf korregiertem umstellen?

Genau – dein Server liefert die richtige Info für den Agent‑Layer, aber Open WebUI versteht dieses Format nicht. Du musst die Antwort also anders schreiben, damit Open WebUI die Tools erkennt. 🔧

Kurz gesagt: Open WebUI will OpenAPI‑kompatible Daten, nicht das Agent‑Layer‑JSON.

So musst du vorgehen:
OpenAPI-Spec erzeugen – ein einfaches Beispiel für ein Tool:
openapi: "3.0.0"
info:
  title: Mein Tool-Server
  version: "1.0.0"
paths:
  /tools/run:
    post:
      summary: Führt ein Tool aus
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                input:
                  type: string
      responses:
        '200':
          description: Erfolg
          content:
            application/json:
              schema:
                type: object
                properties:
                  result:
                    type: string
Server so ändern, dass er diese Spec liefert – z. B. unter /openapi.json:
{
  "openapi": "3.0.0",
  "info": { "title": "Mein Tool-Server", "version": "1.0.0" },
  "paths": {
    "/tools/run": {
      "post": {
        "summary": "Führt ein Tool aus",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": { "type": "object", "properties": { "input": { "type": "string" } } }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Erfolg",
            "content": { "application/json": { "schema": { "type": "object", "properties": { "result": { "type": "string" } } } } }
          }
        }
      }
    }
  }
}
Open WebUI verbinden:
Settings → Tools → Tool Server hinzufügen → URL zu /openapi.json
Open WebUI zeigt dann die Tools automatisch an.