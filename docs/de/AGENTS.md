# KI-Agenten (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · **Deutsch** · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet kann als [Model Context Protocol](https://modelcontextprotocol.io/)-Server (MCP) arbeiten, sodass ein KI-Assistent wie Claude Code Ihre Bibliothek mit denselben Filtern wie die Galerie durchsuchen und untersuchen kann. Der Endpunkt ist schreibgeschützt: Er stellt neun Lesewerkzeuge bereit und ändert nichts an Ihrer Bibliothek.

## Aktivieren

Der Endpunkt ist **standardmäßig deaktiviert**. Setzen Sie `viewer.mcp.enabled` in `scoring_config.json` auf `true` (siehe [Agent-Endpunkt (MCP)](CONFIGURATION.md#agent-endpunkt-mcp)) und starten Sie den Viewer neu oder laden Sie die Konfiguration neu. Solange er deaktiviert ist, antworten `/mcp` und alle `/api/mcp/*`-Routen mit 404.

Der Endpunkt ist `POST /mcp` auf dem Port des Viewers: Streamable HTTP, zustandslos, einfache JSON-Antworten. `GET` antwortet mit 405. In einem Reverse-Proxy sind keine WebSocket-Header nötig.

## Token erstellen

Ein Assistent authentifiziert sich mit einem persönlichen Token, das mit `fct_` beginnt. Erstellen Sie eines mit einer authentifizierten Anfrage (das Token wird **nur einmal** zurückgegeben; Facet speichert nur seinen SHA-256-Hash):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

Die Antwort enthält den Klartext in `token`. `GET /api/mcp/tokens` listet Ihre Tokens auf (nie das Geheimnis), `DELETE /api/mcp/tokens/{id}` widerruft eines. Ein Superadmin kann mit `?all=1` die Tokens aller Besitzer auflisten und beliebige widerrufen. Jeder Besitzer kann höchstens 20 aktive Tokens haben (darüber 412). Diese Routen lehnen die eigenen Zugangsdaten eines Agenten ab, ein Assistent kann also nie Tokens erstellen, auflisten oder widerrufen.

## Claude Code verbinden

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

Die Werkzeuge erscheinen dann als `mcp__facet__search_photos` usw. Verwenden Sie HTTPS, sobald der Viewer über Ihren eigenen Rechner hinaus erreichbar ist, da das Token bei jedem Aufruf in einem Header übertragen wird.

## Berechtigungsstufen

Ein Token wird mit einer Stufe erstellt: `readonly`, `user` oder `edition`. Die **effektive** Stufe wird bei jedem Aufruf neu berechnet, als die niedrigere von Token-Stufe und aktueller Stufe des Besitzers:

- Installationen mit einem Passwort: `user` wird beim Erstellen auf `readonly` begrenzt, da dieser Modus keine mittlere Stufe kennt. Ein `edition`-Token braucht eine Edition-Sitzung und funktioniert nur, solange das Edition-Passwort unverändert bleibt.
- Mehrbenutzer-Installationen: Das `edition`-Token eines später herabgestuften Benutzers fällt auf `user`; eine Beförderung hebt ein Token nie über seine Stufe.
- Offene Installationen (kein Passwort): Tokens sind immer `readonly` und gehören einem gemeinsamen Besitzer `_anonymous`.

Ein Token wird automatisch ungültig, wenn sich die Zugangsdaten seines Besitzers ändern: Viewer- oder Edition-Passwort im Ein-Passwort-Modus, Passwort des Besitzers im Mehrbenutzer-Modus oder Löschen seines Kontos. Es erhält dann am Eingang ein 401.

## Werkzeuge

Alle neun registrierten Werkzeuge sind schreibgeschützt:

| Werkzeug | Funktion |
|------|--------------|
| `search_photos` | Filtert und sortiert die Bibliothek wie die Galerie; die Standard-Ausblendungen des Viewers gelten, sofern der Filter sie nicht setzt (meldet `hidden_summary`) |
| `semantic_search` | Findet Fotos nach Bedeutung oder mit `scope: "text"` nach Wörtern in Bildunterschriften |
| `get_photo` | Vollständige Details eines Fotos anhand seines Pfads (ohne Histogramm) |
| `similar_photos` | Fotos, die einem Foto ähneln, per visueller Einbettung oder nach Farbe |
| `filter_options` | Das Vokabular, das ein Filter akzeptiert: Kameras, Objektive, Tags, Personen, Muster, Kategorien, narrative Momente, Müll-Arten, Metrikbereiche |
| `list_persons` | Erkannte Personen, optional nach Name gefiltert |
| `list_albums` | Alben, die der Besitzer des Tokens sehen kann |
| `library_stats` | Bibliotheksgröße, Zahlen je Typ und Überblick über die Bewertungen |
| `status` | Wer das Token ist, seine effektive Stufe und die Server-Flags |

## Ergebnisse, Limits und Fehler

Jedes Ergebnis ist ein JSON-Umschlag: `{"ok": true, "data": ...}` oder `{"ok": false, "error": "<code>", "message": "..."}`. Listen liefern `data.rows` (ein kompakter, fester Feldsatz pro Foto) plus `total`.

- **Obergrenzen:** höchstens `max_rows` Zeilen und `max_bytes` serialisierte Bytes. Letzte Zeilen werden verworfen und `truncated: true` gesetzt. Ein Ergebnis ohne Zeilen, das `max_bytes` überschreitet, wird zum Fehler `too_large`.
- **Ratenbegrenzung:** `rate_per_min` Aufrufe pro Minute und Token (für schreibende Aufrufe gibt es ein eigenes Budget `write_rate_per_min`). Darüber: `rate_limited` mit `retry_after_s`. Zehn fehlgeschlagene Bearer-Versuche pro Minute von einer Adresse führen zu 429.
- **Fehlercodes:** `forbidden_level` (Endpunkt deaktiviert, ungültiges Token oder zu niedrige Stufe), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`.
- **HTTP-Codes am Eingang:** 401 bei fehlendem oder unbekanntem Token, 403 bei Browser-Anfragen einer anderen Origin, 404 bei deaktiviertem Endpunkt.

## Sicherheitshinweise

- Bildunterschriften, Tags, Dateinamen, Pfade sowie Album- und Personennamen stammen aus Ihrer Bibliothek und können Text enthalten, der einen Assistenten manipulieren soll (Prompt-Injection). Jedes Werkzeug ist mit `facet/untrusted_content` markiert und weist das Modell an, sie als Daten zu behandeln. Geben Sie einem Assistenten, der auch nicht vertrauenswürdige Inhalte liest, keine Möglichkeit, auf das hier Gefundene zu reagieren.
- Tokens laufen nie ab. Widerrufen Sie nicht mehr benötigte.
- Die Protokolle erfassen Token-ID, Werkzeug, Ergebnis und Zeilenzahl, nie Argumente oder das Token.

## Bekannte Einschränkungen

- Auf einer offenen Installation (ohne Passwort) kann jeder, der den Viewer erreicht, die gemeinsamen `_anonymous`-Tokens erstellen und widerrufen. Setzen Sie ein Passwort, bevor Sie den Endpunkt in einem Netzwerk aktivieren.
- Ratenlimits und Zähler fehlgeschlagener Authentifizierungen liegen im Speicher des jeweiligen Prozesses; mit `viewer.py --workers N` zählt jeder Worker getrennt.
- `viewer.mcp.bridge` wird vom Werkzeug `status` gelesen, sonst nutzt es noch nichts.
