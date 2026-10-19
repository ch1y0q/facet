# KI-Agenten (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · **Deutsch** · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet kann als [Model Context Protocol](https://modelcontextprotocol.io/)-Server (MCP) auftreten, sodass ein KI-Assistent wie Claude Code Ihre Bibliothek mit denselben Filtern wie die Galerie durchsuchen und prüfen kann. Er stellt neun Lesewerkzeuge bereit, die nichts in Ihrer Bibliothek ändern, und neun `ui_*`-Werkzeuge, die den bereits geöffneten Browser-Tab steuern (Seite, Filter, Auswahl) und nie Bibliotheksdaten schreiben. Dafür freigegebene Tokens können außerdem [Änderungen vornehmen](#änderungen-vornehmen) (Bewertungen, Markierungen, Tags, Alben, Auswahl und Löschen) und die [Dunkelkammer](#dunkelkammer-auswahlgruppen) bedienen.

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
- Installationen mit einem einzigen Passwort haben keine Stufe `user`: Die effektive Stufe ist `edition` oder `readonly`, daher brauchen die unter [Änderungen vornehmen](#änderungen-vornehmen) mit `user` markierten Werkzeuge dort ebenfalls ein `edition`-Token.
- Jedes Werkzeug hat seine eigene Mindeststufe, die vor jedem Lesen oder Schreiben geprüft wird; ein niedrigeres Token erhält `forbidden_level`.

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

## Änderungen vornehmen

Schreibwerkzeuge stehen neben den Lesewerkzeugen in derselben `/mcp`-Liste. Jedes läuft über die eigenen `/api`-Routen des Viewers, sodass deren Schutzmaßnahmen weiter gelten, und jedes wird auf das Budget `write_rate_per_min` angerechnet. Die Stufe ist die niedrigste effektive Stufe, die das Werkzeug aufrufen darf (siehe [Berechtigungsstufen](#berechtigungsstufen)).

| Werkzeug | Stufe | Was es tut | Grenzen |
|----------|-------|------------|---------|
| `set_rating` | `user` | Setzt die Sternebewertung (0-5) von Fotos | 50 Pfade |
| `set_favorite` | `user` | Markiert Fotos als Favorit oder hebt es auf (Markieren hebt „abgelehnt“ auf) | 50 Pfade |
| `set_rejected` | `user` | Lehnt Fotos ab oder hebt die Ablehnung auf (Ablehnen entfernt Bewertung und Favorit) | 50 Pfade |
| `batch_set_rating` | `edition` | Setzt die Bewertung vieler Fotos | 1000 Pfade oder `filters` |
| `batch_set_favorite` | `edition` | Markiert viele Fotos als Favorit | 1000 Pfade oder `filters` |
| `batch_set_rejected` | `edition` | Lehnt viele Fotos ab | 1000 Pfade oder `filters` |
| `add_tags` | `edition` | Fügt manuelle Tags hinzu (getrennt von den KI-Tags) | 10 Tags; 1000 Pfade oder `filters` |
| `remove_tags` | `edition` | Entfernt manuelle Tags | 10 Tags; 1000 Pfade oder `filters` |
| `create_album` | `edition` | Legt ein leeres Album an (nicht idempotent: zweimal ergibt zwei Alben) | |
| `album_add_photos` | `edition` | Fügt einem Album Fotos hinzu (bereits enthaltene werden ignoriert) | 1000 Pfade |
| `album_remove_photos` | `edition` | Entfernt Fotos aus einem Album; die Fotos selbst bleiben unberührt | 1000 Pfade |
| `junk_list` | `readonly` | Listet Kandidaten der Ausschuss-Suche, optional nur einer `kind` | 100 pro Seite |
| `junk_reject` | `edition` | Lehnt Ausschuss-Kandidaten ab (wie `batch_set_rejected`) | 1000 Pfade |
| `junk_clear` | `edition` | Behält Kandidaten: markiert sie als geprüft und unbedenklich, damit sie die Warteschlange verlassen | 50 Pfade |
| `cull_apply` | `edition` | Kopiert die behaltenen Fotos oder verschiebt bzw. entsorgt die abgelehnten ([Vorschau, dann Bestätigung](#destruktive-aktionen-vorschau-dann-bestätigung)) | 10000 Pfade oder `filters` |
| `delete_photos` | `edition` | Legt die Dateien in den Papierkorb und löscht ihre Bibliothekseinträge ([Vorschau, dann Bestätigung](#destruktive-aktionen-vorschau-dann-bestätigung)) | 1000 Pfade |

- **Die `user`-Werkzeuge brauchen bei einer Installation mit einem einzigen Passwort ein Edition-Token**, da es dort keine mittlere Stufe gibt (siehe [Berechtigungsstufen](#berechtigungsstufen)).
- **Mengensemantik.** Die Werkzeuge pro Foto lesen den aktuellen Zustand und schreiben nur eine Abweichung, ein wiederholter Aufruf ist also harmlos; jeder Pfad meldet `changed` oder `already`. Sie arbeiten einen Pfad nach dem anderen ab und halten beim ersten `library_busy`, `outcome_unknown` oder `forbidden_level` an und melden `affected`, die `results` je Pfad und `not_attempted`. Die Stapelwerkzeuge setzen denselben Zustand.
- **Fotos auswählen.** Die Stapel-, Tag- und `cull_apply`-Werkzeuge nehmen ENTWEDER `paths` ODER `filters` (das Filterobjekt von `search_photos`) plus eine optionale Liste `exclude`. Ein `filters`-Ziel muss `expected_count` mitbringen, die Trefferzahl der Filter vor Anwendung von `exclude` (das `total` von `search_photos`). Facet zählt die Filter zuerst neu und schreibt nichts, wenn die Zahlen abweichen (`invalid_input`, mit `actual_count`).
- **Wessen Zustand.** Bewertungen, Favoriten und Ablehnungen gehören dem Besitzer des Tokens.

### Destruktive Aktionen: Vorschau, dann Bestätigung

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) und `delete_photos` sind mit `destructiveHint` gekennzeichnet und laufen als Probelauf, sofern nicht mit `dry_run: false` aufgerufen.

1. Der Probelauf ändert nichts und listet die Dateien auf, die er kopieren, verschieben oder in den Papierkorb legen würde (lange Listen werden auf `max_rows` gekürzt, mit einem `<key>_count`). Für `move_rejects`, `trash_rejects` und `delete_photos` liefert er außerdem einen `confirm`-Wert, gültig für `confirm_expires_in_s` (5 Minuten) und für eine einzige Verwendung.
2. Der echte Aufruf (`dry_run: false`) muss dieses `confirm` mitgeben. Facet ermittelt Dateimenge und Optionen neu und vergleicht sie mit denen, für die der Wert ausgestellt wurde. Hat sich etwas geändert, ist der Wert ungültig und der Aufruf antwortet `confirmation_required`: erneut einen Probelauf machen.
3. `copy_keeps` braucht kein `confirm`: Es schreibt nur Kopien. Standardmäßig läuft es trotzdem zuerst als Probelauf.

Der `confirm`-Wert ist an das Token, die Aktion und die genaue Dateimenge samt Optionen gebunden. Er liegt im Speicher eines einzelnen Prozesses, ein Neustart verwirft daher alle ausstehenden Werte.

**Empfohlenes Vorgehen:** Zeigen Sie dem Benutzer immer die Zusammenfassung des Probelaufs (Anzahlen und Dateiliste) und holen Sie sich seine ausdrückliche Zustimmung, bevor Sie `dry_run: false` aufrufen. Bestätigen Sie nie aus eigener Initiative.

- `move_rejects` und `trash_rejects` wirken nur auf Fotos, die der Besitzer abgelehnt hat; andere werden als `excluded_by_state` gemeldet. Begleitende RAW- und `.xmp`-Dateien (`include_companions`) und die übrigen Bilder einer Belichtungsreihe oder eines Panoramas (`include_sequence_siblings`) bleiben unberührt, sofern Sie das nicht aktivieren.
- `delete_photos` schickt die Dateien in den Papierkorb des Systems und **löscht ihre Bibliothekseinträge**: Scores, Tags und Bewertungen sind nicht wiederherstellbar, auch wenn die Dateien es sind.
- **Voraussetzungen.** `trash_rejects` und `delete_photos` verlangen `viewer.cull.allow_trash` auf `true` (Standard `false`; sonst wird der Aufruf abgelehnt). Das `target_dir` von `copy_keeps` und `move_rejects` muss unter einem erlaubten Exportort liegen: `viewer.export.allowed_target_dirs` plus Ihre Scan-Verzeichnisse (siehe [Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung)).

## Dunkelkammer (Auswahlgruppen)

Die Dunkelkammer-Werkzeuge spiegeln die Seite `/culling`. Alle brauchen die Stufe `edition`, auch die nur auflistenden.

| Werkzeug | Was es tut |
|----------|------------|
| `list_culling_groups` | Listet Gruppen (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) mit ihren Fotos und Scores, sortierbar und nach Album oder Zeitraum eingrenzbar |
| `culling_profiles` | Die genrebezogenen Auswahl-Voreinstellungen und die Standardvoreinstellung |
| `suggest_culling_profile` | Nennt die zu einem Album oder Aufnahmezeitraum passende Voreinstellung |
| `keeper_hints` | Hinweise pro Foto „in dieser Serie gibt es ein besseres Bild“ für bis zu 100 Pfade (leer, wenn kein Keeper-Kopf trainiert ist) |
| `auto_cull` | Automatische Auswahl eines Bereichs mit Keeper-Budget: erst Vorschau, dann Anwenden mit dem `confirm`-Wert |
| `confirm_culling_groups` | Bestätigt bis zu 20 Gruppen: behält ihre `keep_paths`, lehnt den Rest ihrer `paths` ab |

- **Eine Gruppe wird durch das Paar `(type, group_id)` identifiziert**, nie durch `group_id` allein: Die IDs ähnlicher Gruppen werden beim Zusammenführen mit Serien versetzt.
- **Belichtungsreihen, Panoramen und HDR-Panoramen bleiben komplett erhalten.** In `confirm_culling_groups` muss `keep_paths` für diese Typen gleich `paths` sein (sonst `invalid_input`), und `auto_cull` teilt sie nie auf.
- **Ein leeres `keep_paths` lehnt jedes Bild der Gruppe ab.** Der erste Aufruf antwortet dann `confirmation_required` mit einem `confirm`-Wert; zeigen Sie das dem Benutzer und wiederholen Sie den Aufruf mit diesem Wert. Hält ein Stapel bei `forbidden_level`, `library_busy` oder `rate_limited` an, werden die bereits erledigten Gruppen gemeldet.
- **`auto_cull` zeigt standardmäßig eine Vorschau** und liefert die Aufteilung in Behalten und Ablehnen je Gruppe plus einen `confirm`-Wert (nur wenn etwas abgelehnt würde). Das Anwenden berechnet den Plan neu und weist ihn mit `confirmation_required` ab, wenn er sich seit der Vorschau geändert hat oder zu groß ist, um als eine Menge bestätigt zu werden (mit `album_id`, `date_from` und `date_to` oder `group_by` eingrenzen). Abgelehnte Bilder speisen den persönlichen Ranker wie jede manuelle Auswahl.
- Rufen Sie `ui_show_culling_group` auf, um dem Benutzer eine Gruppe in seinem offenen Tab zu zeigen (siehe [Den geöffneten Tab steuern](#den-geöffneten-tab-steuern)).

## Ergebnisse, Limits und Fehler

Jedes Ergebnis ist ein JSON-Umschlag: `{"ok": true, "data": ...}` oder `{"ok": false, "error": "<code>", "message": "..."}`. Listen liefern `data.rows` (ein kompakter, fester Feldsatz pro Foto) plus `total`.

- **Obergrenzen:** höchstens `max_rows` Zeilen und `max_bytes` serialisierte Bytes. Letzte Zeilen werden verworfen und `truncated: true` gesetzt. Ein Ergebnis ohne Zeilen, das `max_bytes` überschreitet, wird zum Fehler `too_large`.
- **Ratenlimit:** `rate_per_min` Aufrufe pro Minute und Token für Lesezugriffe. Schreibwerkzeuge verbrauchen ein getrenntes Budget `write_rate_per_min` (Standard 30), damit Suchen Schreibzugriffe nicht aushungern und umgekehrt; der Probelauf von `cull_apply` und `delete_photos` zählt als Schreibzugriff, eine `auto_cull`-Vorschau als Lesezugriff. Darüber hinaus: `rate_limited` mit `retry_after_s`. Zehn fehlgeschlagene Bearer-Versuche pro Minute von einer Adresse beantwortet der Server mit 429.
- **Fehlercodes:** `forbidden_level` (Endpunkt deaktiviert, ungültiges Token oder zu niedrige Stufe), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Die neueren Codes:** `confirmation_required` (ein destruktiver Aufruf hat keinen gültigen `confirm`-Wert für genau diese Menge: erneut einen Probelauf machen, dem Benutzer das Ergebnis zeigen, dann wiederholen), `outcome_unknown` (ein Schreibvorgang hat das Zeitlimit überschritten oder die Verbindung brach ab, er kann also erfolgt sein oder nicht: vor einer Wiederholung den Zustand neu lesen, nie blind wiederholen), `library_busy` (die Bibliothek ist mit einem anderen Job beschäftigt: gleich noch einmal versuchen).
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
