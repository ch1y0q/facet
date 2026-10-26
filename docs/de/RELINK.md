# Ein fehlendes Foto nach einem ausdrücklichen Umzug neu verknüpfen

`python database.py --relink-photos` aktualisiert vorhandene Pfade in der Facet-Datenbank, nachdem Sie Dateien selbst verschoben haben. Es verschiebt, kopiert, löscht oder bearbeitet niemals Originale oder Sidecar-Dateien und kontaktiert Immich nie. Es ist ein Offline-Wartungsbefehl für Betreiber mit Zugriff auf die Datenbank und die konfigurierten Ordner. Beenden Sie zuerst Viewer, Scanner und externe Dateieditoren, sichern Sie die Datenbank und prüfen Sie den Plan, bevor Sie ihn anwenden.

Das Anwenden hält die Bibliothekswartungssperre von Facet bis zum Ende des Datenbankschreibvorgangs. Ein anderer Bibliotheksauftrag führt zu Exitcode 75, ohne dass Datenbank oder Medien verändert werden; eine unbenutzbare Sperre führt zu Exitcode 1. Die Vorschau bleibt schreibgeschützt und nimmt keine Bibliothekssperre. Diese Sperre koordiniert Aufträge auf einem Host; die Offline-Anforderungen gelten weiterhin für andere Hosts und externe Editoren.

Die vorhandene Datenbank enthält keinen kryptografischen Hash der Bytes der Originaldatei. `phash` und die Graustufensignaturen manueller Gesichter beweisen keine Byte-Identität. Jeder Plan nennt deshalb `original_bytes_unknown`. Der SHA-256 des Ziels identifiziert nur die neue Datei, die in der Vorschau gezeigt wurde. Das Anwenden bekräftigt ausdrücklich, dass Sie die richtige verschobene Datei unabhängig identifiziert haben; es ist nie eine automatisch verifizierte Übereinstimmung. Eine falsche Angabe kann vorhandene Annotationen an das falsche Bild hängen.

Das Verschieben oder Umbenennen eines ganzen Verzeichnisses liegt außerhalb dieses begrenzten Modus, wenn der alte übergeordnete Ordner nicht mehr existiert. Fehlende Verzeichnisse lassen einen beabsichtigten Umzug nicht von Offline-Speicher unterscheiden. Legen Sie keine leeren alten Elternordner neu an, um diese Prüfung zu umgehen.

## Vorschau, Prüfung, dann Anwenden

Erstellen Sie eine JSON-Liste mit exakten kanonischen absoluten Pfaden. Eine fehlende Quelle muss bereits in Facet registriert sein; ein Ziel muss als Bild existieren und darf noch keine Fotozeile haben:

```json
[
  {
    "old": "/photos/before/portrait.jpg",
    "new": "/photos/after/portrait-renamed.jpg",
    "companions": [
      {
        "old": "/photos/before/portrait.jpg.xmp",
        "new": "/photos/after/portrait-renamed.jpg.xmp",
        "kind": "sidecar_full"
      }
    ]
  }
]
```

```sh
# Schreibgeschützte Datenbankvorschau; erzeugt ein privates (0600), exklusives Prüfartefakt.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Prüfen Sie in relink-plan.json jeden alten/neuen Pfad, das Identitätslabel mit unbekannten Bytes, den Ziel-Hash, die
# Abmessungen, Referenzen, Begleitdateien und die Sichtbarkeitsrichtlinie.
# Ersetzen Sie REVIEWED_PLAN_ID nach der Prüfung durch die exakte plan_id dieses Artefakts.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

Im Mehrbenutzerbetrieb ist zusätzlich `--user alice` in beiden Befehlen erforderlich. Das ist ein Bereichsselektor für Betreiber, kein Ersatz für die Zugriffskontrolle des Betriebssystems und keine authentifizierte API. Beide Pfade müssen für diesen Benutzer sichtbar sein, und die Menge **aller** Benutzer, die das Foto sehen können, muss identisch bleiben. Von privat zu geteilt oder andere benutzerübergreifende Verschiebungen werden abgelehnt. Beide Pfade müssen in ausdrücklich konfigurierten Scan-, Benutzer- oder gemeinsamen Verzeichnissen liegen. Leere Wurzelkonfiguration, nicht erreichbare Wurzeln und `viewer.path_mapping` werden abgelehnt; dieses erste Werkzeug unterstützt nur native kanonische Pfade.

Das Anwenden prüft den gesamten geprüften Plan innerhalb einer einzigen SQLite-Schreibtransaktion erneut. Geänderte Zieldateien, Fotozeilen, Annotationen, Schemata, Datenbank-Inodes oder Sichtbarkeitsrichtlinien erfordern eine neue Vorschau. Ein fehlgeschlagener Stapel macht alle seine Datenbankschreibvorgänge rückgängig. Ein erfolgreiches Anwenden gibt einen Beleg mit der Plan-ID aus. Es wird weder eine neue logische Asset-ID noch eine Zuordnung zu einer entfernten UUID gespeichert.

## Was dem Foto folgt

Foto-Rowids, Bewertungen/Keep/GPS, Tags, Gesichts-/Personen-IDs und manuelle UUIDs, Vergleiche, gelernte Scores, Präferenzen pro Benutzer, Überschreibungen, feste Albummitgliedschaften/Cover/Kundenauswahlen, Extraktions-Snapshots und Vektor-Embeddings behalten ihre Zuordnungen. Vorhandene Fremdschlüssel auf photos werden aus dem tatsächlichen Schema ermittelt; eine neue nicht registrierte Pfadspalte wird abgelehnt, statt stillschweigend verwaist zu werden. Abgeleitete Statistiken werden ungültig gemacht; dauerhafter Trainingszustand bleibt erhalten.

Einträge des Organisationsverlaufs behalten ihre ursprünglichen historischen Pfad-Nutzdaten. Vorhandene Trigger bei Pfadänderungen schalten die Revisionsuhr weiter und machen private Revisions-Caches ungültig; ein Eintrag, der sich auf den alten Pfad bezieht, kann nach dem Neuverknüpfen möglicherweise nicht mehr erscheinen oder zurückgesetzt werden. Das Neuverknüpfen erhält die aktuellen Annotationswerte und Zuordnungen, schreibt vergangene Aktionen aber nicht um, damit sie auf einen anderen Pfad anwendbar werden.

Alle manuellen Rechtecke bleiben erhalten, müssen aber auf dem neuen Pfad geprüft werden. Die grobe alte Signatur kann die Pixel des fehlenden Originals nicht beweisen. Eine Markierung `relink_unverified` verhindert, dass gewöhnliche Signaturprüfungen diesen Prüfstatus löschen; öffnen Sie den Editor und speichern Sie jedes Rechteck ausdrücklich gegen den neuen Frame, bevor es exportiert werden oder Erkennungen unterdrücken kann. Vorhandene Rechteck- und Personen-IDs bleiben erhalten.

Der Immich-Push-/Ausstehend-Zustand bleibt unverändert: Eine lokale Dateinamenbehauptung kann keine entfernte Identität verifizieren. Keine entfernte Bewertung, kein Löschen, keine Albummitgliedschaft und keine UUID wird neu verknüpft. Prüfen Sie die entfernte Zuordnung getrennt, bevor Sie synchronisieren. Historische Scan-Fehlerpfade bleiben historisch; Filterprädikate intelligenter Alben und logische Sequenzgruppenschlüssel werden nicht stillschweigend umgeschrieben. Statische Mitgliedschaften und Sequenz-/Serienbild-/Duplikat-Gruppenwerte bleiben unverändert.

## Ausdrückliche Begleitdateien und Ablehnungen

Führen Sie Begleitdateien ausdrücklich auf; das Werkzeug kann nicht indizierte RAW-/XMP-Dateien, die aus dem alten Verzeichnis verschwunden sind, nicht entdecken. `sidecar_full` bedeutet `photo.ext.xmp`, `sidecar_basename` bedeutet `photo.xmp`, `sidecar_facet` bedeutet `photo.ext.facet.xmp`, und `raw` behält ein ausdrücklich angegebenes RAW-Paar im selben Verzeichnis mit gleichem Stamm bei, das mit dem aktuellen Culling kompatibel ist. Diese Dateinamenregeln validieren eine deklarierte Beziehung; sie beweisen keine Dateiidentität. Indizierte RAW-Fotos benötigen einen eigenen Relink-Eintrag auf oberster Ebene, damit ihre Annotationen erhalten bleiben.

Nicht aufgeführte Sidecars oder RAW-Begleitdateien am Ziel werden abgelehnt, einschließlich Facet-Fallback-Paketen und Schreibweisen mit abweichender Groß-/Kleinschreibung. Mehrere RAW-Kandidaten und mehrdeutige XMP-Zuordnung werden abgelehnt, darunter `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp` sowie Kollisionen von Basisnamen und Groß-/Kleinschreibung oder Unicode. Keine Begleitdatei wird nach dem ersten Treffer zugewiesen. Die Bytes vorhandener Begleitdateien werden gehasht, erneut geprüft und unverändert gelassen. Nicht aufgeführte fehlende Begleitdateien bleiben unbekannt; werten Sie eine leere Liste nicht als Beweis, dass es keine gab.

Abgelehnt werden Kopien mit noch vorhandenem alten Original, fehlende oder unlesbare alte Elternordner, bereits vorhandene Zielfotos oder abhängige Zeilen, wiederholte Zuordnungen, doppelte Fotoinhalte oder Ziel-Inodes, reine Groß-/Kleinschreibungs- oder Unicode-Änderungen, Symlinks sowie Änderungen von Erweiterung oder Format. Gespeicherte kanonische Abmessungen müssen, sofern bekannt, zum dekodierten Ziel passen. Es läuft keine Ähnlichkeits- oder Dateinamensuche und keine automatische Abstimmung.

Grenzen: 100 Fotos, 300 ausdrücklich benannte Dateien, 512 MiB pro Datei, 2 GiB Dateibytes insgesamt und 2 MiB JSON-Eingabe bzw. Prüfplan. Verkleinern Sie einen Stapel, wenn eine Grenze erreicht wird. Die Datenbanktransaktion ist atomar; das Dateisystem ist gegenüber anderen Anwendungen nicht gesperrt, daher die Offline-Anforderung. Die Fixture-Tests behaupten keinen Rundlauf mit einer echten externen Anwendung oder einem entfernten Server.

Lesbare Verzeichnisse beweisen **nicht**, dass ein Speicher eingehängt ist. Ein nicht eingehängtes Volume kann einen leeren, lesbaren Einhängepunkt hinterlassen, der von einem tatsächlich leeren Verzeichnis nach dem Umzug nicht zu unterscheiden ist. Der Plan meldet ausdrücklich `source_mount_status: not_verified`; bestätigen Sie unabhängig, dass jede Quelle verschoben und nicht nur nicht verfügbar wurde, bevor Sie die Identität bestätigen. Der Befehl erkennt nicht jeden Offline-Volume-Zustand. Prüfpläne enthalten private vollständige Pfade und die Benutzerbereichsrichtlinie; `--plan-out` legt sie exklusiv mit Modus 0600 unter POSIX an.

| Option | Zweck |
|---|---|
| `--db` | Vorhandene Datenbank |
| `--config` | Aufgelöste Konfiguration |
| `--user` | Konfigurierter Benutzer im Mehrbenutzerbetrieb erforderlich |
| `--mapping` | Explizite alte/neue JSON-Pfade; Vorschau |
| `--plan-out` | Neue private Plandatei ohne Überschreiben |
| `--apply-plan` | Geprüften Plan anwenden |
| `--ack-plan` | Exakter Hash des geprüften Plans |
| `--acknowledge-unverified-identity` | Explizite Bestätigung trotz unbekannter Originalbytes |
