# KI-Agenten (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · **Deutsch** · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet kann als [Model Context Protocol](https://modelcontextprotocol.io/)-Server (MCP) arbeiten, sodass ein KI-Assistent wie Claude Code Ihre Bibliothek mit denselben Filtern wie die Galerie durchsuchen und untersuchen kann. Er stellt neun Lesewerkzeuge bereit, die nichts an Ihrer Bibliothek ändern, sowie neun `ui_*`-Werkzeuge, die den bereits geöffneten Browser-Tab steuern (Seite, Filter, Auswahl) und nie Bibliotheksdaten schreiben.

## Aktivieren

Der Endpunkt ist **standardmäßig deaktiviert**. Setzen Sie `viewer.mcp.enabled` in `scoring_config.json` auf `true` (siehe [Agent-Endpunkt (MCP)](CONFIGURATION.md#agent-endpunkt-mcp)) und starten Sie den Viewer neu oder laden Sie die Konfiguration neu. Solange er deaktiviert ist, antworten `/mcp` und alle `/api/mcp/*`-Routen mit 404.

Der Endpunkt ist `POST /mcp` auf dem Port des Viewers: Streamable HTTP, zustandslos, einfache JSON-Antworten. `GET` antwortet mit 405. Nur die Tab-Brücke `/api/mcp/bridge` ist ein WebSocket; siehe [Den geöffneten Tab steuern](#den-geöffneten-tab-steuern).

## Token erstellen

Am einfachsten geht es im Browser. Öffnen Sie bei aktivem `viewer.mcp.enabled` das Kontomenü und wählen Sie **Assistent verbinden**. Geben Sie unter **Token erstellen** einen **Name** ein und wählen Sie **Was der Assistent darf**: **Nur lesen und steuern**, dazu **In meinem Namen handeln** oder **Volle Bearbeitung**, wenn Ihre Sitzung diese Stufe hat (ein Token kann die Sitzung, die es erstellt, nicht übertreffen). Klicken Sie auf **Token erstellen**: Das Token erscheint nur einmal unter **Ihr neues Token**, kopieren Sie es also sofort. **Zugriffstoken** listet Ihre Token mit der letzten Nutzung und widerruft eines. **Zu Claude Code hinzufügen** zeigt den fertigen Claude-Code-Befehl (siehe unten), und **Dieser Tab** sagt, ob dieser Tab verbunden ist und Assistenten ihn steuern können. Die Stufenliste beschränkt sich auf das, was der Server gewährt: Eine offene Installation bietet nur **Nur lesen und steuern**, **In meinem Namen handeln** erscheint nur bei Mehrbenutzer-Installationen und **Volle Bearbeitung** nur in einer Bearbeitungssitzung. Nach dem Erstellen nennt der Dialog die tatsächlich gewährte Stufe („Gewährter Zugriff: {level}“).

Alternative per Skript (curl):

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

Die neun Datenwerkzeuge sind schreibgeschützt:

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

## Den geöffneten Tab steuern

Neben den Datenwerkzeugen listet der Server immer neun `ui_*`-Werkzeuge, die auf den Facet-Tab wirken, den Sie im Browser geöffnet haben: Sie wechseln die Seite, ändern Filter oder Auswahl und lesen zurück, was Sie sehen. Sie schreiben nie Bibliotheksdaten, ein `readonly`-Token genügt also.

| Werkzeug | Was es tut |
|----------|------------|
| `ui_navigate` | Zu einer Seite wechseln (Galerie, Personen, Alben, Statistik, ...) |
| `ui_set_gallery_filters` | Einen Patch in Filter und Sortierung der Galerie einmischen (`null` entfernt einen Filter, `replace: true` beginnt ohne Filter) |
| `ui_get_gallery_view` | Route, aktive Filter, Gesamttreffer, die ersten sichtbaren Fotopfade und die Zahl der ausgewählten Fotos |
| `ui_open_photo` | Ein Foto öffnen |
| `ui_select_photos` | Explizite `paths` auswählen, oder mit `select_view: true` die ganze gefilterte Ansicht, im Modus `replace`, `add` oder `remove` |
| `ui_clear_selection` | Die Auswahl leeren |
| `ui_get_selection` | Der `scope` (`paths` oder `view`) und der `count`, mit den `paths` oder bei einer Ansicht den `filters` und `excluded_paths` |
| `ui_next_page` | Die nächste Galerieseite laden |
| `ui_show_culling_group` | Die Dunkelkammer auf einer Gruppe öffnen, identifiziert durch `(type, group_id)` (Edition-Konten) |

So funktioniert es:

- Solange Sie angemeldet sind und `viewer.mcp.enabled` und `viewer.mcp.bridge` beide `true` sind, öffnet jeder Facet-Tab einen WebSocket gleichen Ursprungs zu `/api/mcp/bridge` und authentifiziert sich in seiner ersten Nachricht mit Ihrer Sitzung. Die Brücke ist standardmäßig aktiv; setzen Sie `viewer.mcp.bridge` auf `false`, um sie abzuschalten, dann antworten die `ui_*`-Werkzeuge mit einem eindeutigen Fehler.
- Ein Werkzeug erreicht nur die Tabs des Token-Besitzers. Bei einem einzelnen Passwort sind alle Sitzungen derselbe Benutzer, bei einer offenen Installation gehört jeder Tab dem gemeinsamen Benutzer `_anonymous`.
- Sind mehrere Tabs offen, wird der zuletzt fokussierte verwendet, und das Feld `tab` des Ergebnisses sagt das. Mit `tab_id` (von `status` aufgelistet) wählen Sie einen anderen.
- Ein Tab lehnt ab, was sein Konto nicht darf (zum Beispiel `/culling` für ein Konto ohne Edition), und das Werkzeug gibt diese Ablehnung zurück.
- Was ein Tab zurückschickt, ist nicht vertrauenswürdig: Tiefe, Zeichenketten- und Listenlänge sind begrenzt, und alles wird durch `max_bytes` gedeckelt.
- Fehler: `no_tab` (kein Tab verbunden oder Brücke aus), `tab_timeout` (keine Antwort innerhalb von `call_timeout_s`) und `tab_outdated` (der geöffnete Tab kennt das Werkzeug nicht; laden Sie die Seite nach einem Facet-Update neu).
- Ein Reverse-Proxy muss das WebSocket-Upgrade für `/api/mcp/bridge` weiterreichen; siehe [Deployment](DEPLOYMENT.md). Schreibt er den `Host`-Header um, tragen Sie den öffentlichen Ursprung in `viewer.mcp.allowed_origins` ein (zum Beispiel `["https://photos.example.com"]`), denn der Ursprung der Seite muss zum Host passen oder aufgelistet sein.
- Das Tab-Register gilt pro Prozess, daher braucht die Brücke einen einzigen Worker (der Standard).

Ergänzend:

- `ui_set_gallery_filters` führt zuerst zur Galerie, wenn eine andere Seite offen ist, und wendet dann den Patch an. Ein Patch, der einen Filter nennt, den der Tab nicht steuern kann, wird insgesamt abgelehnt (`invalid_input`); nutzen Sie dafür `search_photos`.
- `ui_get_gallery_view`, `ui_next_page` und `ui_select_photos` mit `select_view` brauchen die Galerie (oder ein Album) als offene Seite, sonst antworten sie `no_active_view`; rufen Sie zuerst `ui_navigate` nach `/` auf. Übergeben Sie `ui_select_photos` genau eines von `paths` und `select_view`.
- `no_tab` heißt auch, dass kein Facet-Tab offen ist: Öffnen Sie Facet in einem Browser und melden Sie sich an. **Dieser Tab** im Dialog **Assistent verbinden** zeigt den Verbindungsstatus samt Tab-ID.
- Ein Tab verbindet sich nicht mehr neu, sobald seine Sitzung abgelehnt wurde (erneut anmelden), und wartet, bis Sie zu ihm zurückkehren, wenn ein anderer Ihrer Tabs übernommen hat.
- Die Tab-Brücke verbindet sich nur, wenn der Server sie als verfügbar meldet (der Endpunkt ist an und `viewer.mcp.bridge` ist true); bei abgeschalteter Brücke verbinden sich Tabs gar nicht.
- `ui_set_gallery_filters` lehnt einen unbekannten Filternamen mit `invalid_input` ab, ebenso einen Patch mit sowohl `category` als auch `type` oder sowohl `person` als auch `person_id`. Er bietet nur die Filter an, die die Galerie anzeigen kann; für die übrigen nutzen Sie `search_photos`.
- `ui_navigate` öffnet nur die statischen Seiten der App: Anmeldeseite, geteilte Seiten, externe URLs und unbekannte Pfade werden abgelehnt (`invalid_input`), und Seiten nur für die Bearbeitung werden einer Sitzung ohne Bearbeitung verweigert.
- `ui_select_photos` im Modus `remove` unter einer Auswahl der ganzen Ansicht ignoriert Pfade außerhalb der geladenen Ansicht und listet sie im Ergebnis als `not_in_view`.

## WebMCP im Tab (Browser-Agenten)

Unabhängig vom Endpunkt `/mcp` bietet ein angemeldeter Tab dieselben `ui_*`-Werkzeuge auch Agenten an, die im Browser selbst laufen, über die W3C-API [WebMCP](https://webmachinelearning.github.io/webmcp/) (`navigator.modelContext`). Ein browsernativer Assistent sieht also genau die oben aufgeführten Werkzeuge, führt sie im Tab aus, den Sie ansehen, und braucht kein Token.

- **Nur im sicheren Kontext.** Facet registriert die Werkzeuge nur über HTTPS oder auf `localhost`. Über einfaches HTTP werden sie nicht angeboten, und der Dialog **Assistent verbinden** weist darauf hin; die tokenbasierte Verbindung oben funktioniert weiter.
- Registriert, wenn `viewer.mcp.enabled` true ist und Sie angemeldet sind, und beim Abmelden entfernt.
- Die Werkzeuge tun dasselbe und sind durch dieselbe Kontostufe begrenzt wie in der obigen Tabelle.

## Ergebnisse, Limits und Fehler

Jedes Ergebnis ist ein JSON-Umschlag: `{"ok": true, "data": ...}` oder `{"ok": false, "error": "<code>", "message": "..."}`. Listen liefern `data.rows` (ein kompakter, fester Feldsatz pro Foto) plus `total`.

- **Obergrenzen:** höchstens `max_rows` Zeilen und `max_bytes` serialisierte Bytes. Letzte Zeilen werden verworfen und `truncated: true` gesetzt. Ein Ergebnis ohne Zeilen, das `max_bytes` überschreitet, wird zum Fehler `too_large`.
- **Ratenbegrenzung:** `rate_per_min` Aufrufe pro Minute und Token (für schreibende Aufrufe gibt es ein eigenes Budget `write_rate_per_min`). Darüber: `rate_limited` mit `retry_after_s`. Zehn fehlgeschlagene Bearer-Versuche pro Minute von einer Adresse führen zu 429.
- **Fehlercodes:** `forbidden_level` (Endpunkt deaktiviert, ungültiges Token oder zu niedrige Stufe), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **HTTP-Codes am Eingang:** 401 bei fehlendem oder unbekanntem Token, 403 bei Browser-Anfragen einer anderen Origin, 404 bei deaktiviertem Endpunkt.

## Sicherheitshinweise

- Bildunterschriften, Tags, Dateinamen, Pfade sowie Album- und Personennamen stammen aus Ihrer Bibliothek und können Text enthalten, der einen Assistenten manipulieren soll (Prompt-Injection). Jedes Werkzeug ist mit `facet/untrusted_content` markiert und weist das Modell an, sie als Daten zu behandeln. Geben Sie einem Assistenten, der auch nicht vertrauenswürdige Inhalte liest, keine Möglichkeit, auf das hier Gefundene zu reagieren.
- Tokens laufen nie ab. Widerrufen Sie nicht mehr benötigte.
- Die Protokolle erfassen Token-ID, Werkzeug, Ergebnis und Zeilenzahl, nie Argumente oder das Token.

## Bekannte Einschränkungen

- Auf einer offenen Installation (ohne Passwort) kann jeder, der den Viewer erreicht, die gemeinsamen `_anonymous`-Tokens erstellen und widerrufen. Setzen Sie ein Passwort, bevor Sie den Endpunkt in einem Netzwerk aktivieren. Die Tab-Brücke verschärft das: Ein Nicht-Browser-Client kann einen erfundenen `Origin` und ein Null-Token senden, einen fokussierten `_anonymous`-Tab registrieren, `ui_*`-Aufrufe mit beliebigen Daten beantworten und über die Grenze von 8 Tabs echte Tabs verdrängen.
- Ratenlimits und Zähler fehlgeschlagener Authentifizierungen liegen im Speicher des jeweiligen Prozesses; mit `viewer.py --workers N` zählt jeder Worker getrennt.
- Das Tab-Register liegt im Arbeitsspeicher eines einzelnen Prozesses. Verwenden Sie einen einzigen Worker (`viewer.py --workers 1`, der Standard), wenn Sie `ui_*`-Werkzeuge nutzen; bei mehreren Workern kann ein Aufruf einen Prozess erreichen, der Ihren Tab nicht kennt, und `no_tab` melden.
- Ein Benutzer kann höchstens 8 Tabs verbunden haben; ein neunter schließt den ältesten.
