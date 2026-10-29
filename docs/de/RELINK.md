# Ein fehlendes Foto nach einem ausdrücklichen Umzug neu verknüpfen

`python database.py --relink-photos` aktualisiert die Pfade in der Facet-Datenbank, nachdem Sie Dateien selbst verschoben haben. Es verschiebt, kopiert, löscht oder bearbeitet niemals Originale oder Sidecar-Dateien und kontaktiert Immich nie. Es ist ein Offline-Wartungsbefehl.

Bevor Sie einen Plan anwenden:

- Beenden Sie Viewer, Scanner und externe Dateieditoren.
- Sichern Sie die Datenbank.
- Prüfen Sie den Plan.

Das Anwenden nimmt die Bibliothekssperre von Facet. Läuft ein anderer Bibliotheksauftrag, endet der Befehl mit Exitcode 75 und ändert nichts; eine unbenutzbare Sperre führt zu Exitcode 1. Die Vorschau ist schreibgeschützt und nimmt keine Sperre. Die Sperre deckt nur Aufträge auf einem Host ab.

> **Warnung:** Facet speichert keinen Hash der Bytes der Originaldatei und kann daher nicht beweisen, dass die neue Datei die verschobene ist. Jeder Plan nennt `original_bytes_unknown`; `phash` und die Signaturen manueller Gesichter beweisen keine Identität. Der SHA-256 des Ziels identifiziert nur die Datei, die Sie in der Vorschau gesehen haben. Das Anwenden bekräftigt, dass Sie die Übereinstimmung selbst geprüft haben. Eine falsche Angabe hängt vorhandene Annotationen an das falsche Bild.

Das Verschieben oder Umbenennen eines ganzen Verzeichnisses wird nicht unterstützt, wenn der alte übergeordnete Ordner nicht mehr existiert. Legen Sie keine leeren alten Elternordner neu an, um diese Prüfung zu umgehen.

## Vorschau, Prüfung, dann Anwenden

Erstellen Sie eine JSON-Liste mit exakten kanonischen absoluten Pfaden. Jede Quelle muss bereits in Facet registriert sein. Jedes Ziel muss als Bild existieren und darf noch keine Fotozeile haben:

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

Im Mehrbenutzerbetrieb fügen Sie beiden Befehlen `--user alice` hinzu. Es wählt, wessen Bereich geprüft wird; es ist keine Zugriffskontrolle. Regeln:

- Beide Pfade müssen für diesen Benutzer sichtbar sein.
- Die Menge **aller** Benutzer, die das Foto sehen können, muss identisch bleiben. Von privat zu geteilt und andere benutzerübergreifende Verschiebungen werden abgelehnt.
- Beide Pfade müssen in ausdrücklich konfigurierten Scan-, Benutzer- oder gemeinsamen Verzeichnissen liegen.
- Leere Wurzelkonfiguration, nicht erreichbare Wurzeln und `viewer.path_mapping` werden abgelehnt. Unterstützt werden nur native kanonische Pfade.

Das Anwenden prüft den gesamten Plan in einer einzigen Datenbanktransaktion erneut. Haben sich Zieldateien, Fotozeilen, Annotationen, Schema, Datenbankdatei oder Sichtbarkeit geändert, führen Sie eine neue Vorschau aus. Ein fehlgeschlagener Stapel macht alle seine Datenbankschreibvorgänge rückgängig. Ein erfolgreiches Anwenden gibt einen Beleg mit der Plan-ID aus.

## Was dem Foto folgt

Diese Daten behalten ihre Zuordnung zum Foto:

- Foto-IDs, Bewertungen, Keep und GPS
- Tags, Gesichter, Personen-IDs und manuelle Gesichts-UUIDs
- Vergleiche, gelernte Scores und Präferenzen pro Benutzer
- Überschreibungen, feste Albummitgliedschaften, Cover und Kundenauswahlen
- Extraktions-Snapshots und Vektor-Embeddings
- Gruppenwerte für Serienbilder, Duplikate und Sequenzen

Abgeleitete Statistiken werden ungültig gemacht; der Trainingszustand bleibt erhalten.

Was sich nicht ändert:

- **Der Rückgängig-Verlauf** behält seine alten Pfade. Ein Eintrag für den alten Pfad erscheint nach dem Neuverknüpfen möglicherweise nicht mehr oder lässt sich nicht mehr zurücksetzen.
- **Manuelle Gesichtsrechtecke** bleiben erhalten, werden aber mit `relink_unverified` markiert. Öffnen Sie den Editor und speichern Sie jedes Rechteck gegen den neuen Frame, bevor es exportiert werden oder Erkennungen unterdrücken kann.
- **Immich**-Push- und Ausstehend-Zustand bleiben unverändert; keine entfernte Bewertung, kein Album und keine UUID wird neu verknüpft. Prüfen Sie die entfernte Zuordnung selbst, bevor Sie synchronisieren.
- **Scan-Fehlerverlauf, Filter intelligenter Alben und Sequenzgruppenschlüssel** werden nicht umgeschrieben.

## Ausdrückliche Begleitdateien und Ablehnungen

Führen Sie Begleitdateien selbst auf; das Werkzeug kann RAW- oder XMP-Dateien, die aus dem alten Verzeichnis verschwunden sind, nicht finden. Arten von Begleitdateien:

| Art | Datei |
|---|---|
| `sidecar_full` | `photo.ext.xmp` |
| `sidecar_basename` | `photo.xmp` |
| `sidecar_facet` | `photo.ext.facet.xmp` |
| `raw` | RAW-Paar im selben Verzeichnis mit gleichem Stamm |

Diese Regeln prüfen die deklarierte Beziehung; sie beweisen keine Identität. Ein indiziertes RAW-Foto braucht einen eigenen Eintrag auf oberster Ebene, damit seine Annotationen erhalten bleiben. Vorhandene Begleitdateien werden gehasht und unverändert gelassen. Eine leere Liste von Begleitdateien beweist nicht, dass es keine gab.

Facet lehnt ab:

- nicht aufgeführte Sidecars oder RAW-Begleitdateien am Ziel, einschließlich Facet-Fallback-Paketen und Schreibweisen mit abweichender Groß-/Kleinschreibung
- mehrere RAW-Kandidaten oder mehrdeutige XMP-Zuordnung, z. B. `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp` oder `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, sowie Kollisionen von Basisnamen, Groß-/Kleinschreibung oder Unicode
- Kopien, bei denen das alte Original noch vorhanden ist
- fehlende oder unlesbare alte Elternordner
- Ziele, die bereits Foto- oder abhängige Zeilen haben
- wiederholte Zuordnungen, doppelte Fotoinhalte oder Ziel-Inodes
- reine Groß-/Kleinschreibungs- oder Unicode-Umbenennungen, Symlinks sowie Änderungen von Erweiterung oder Format
- ein dekodiertes Ziel, dessen Abmessungen von den gespeicherten abweichen, sofern diese bekannt sind

Es läuft keine Ähnlichkeits- oder Dateinamensuche.

Grenzen pro Stapel: 100 Fotos, 300 benannte Dateien, 512 MiB pro Datei, 2 GiB insgesamt und 2 MiB für die JSON-Eingabe bzw. den Plan. Teilen Sie den Stapel auf, wenn Sie eine Grenze erreichen. Der Datenbankschreibvorgang ist atomar, andere Anwendungen können die Dateien aber weiterhin ändern; deshalb muss der Auftrag offline laufen.

> **Warnung:** Ein lesbares Verzeichnis beweist nicht, dass der Speicher eingehängt ist. Ein nicht eingehängtes Volume kann wie ein leerer Ordner aussehen. Der Plan meldet `source_mount_status: not_verified`; bestätigen Sie, dass jede Quelle wirklich verschoben wurde, bevor Sie die Identität bekräftigen. Der Befehl erkennt nicht jeden Offline-Volume-Zustand.

Plandateien enthalten vollständige private Pfade und den Benutzerbereich. `--plan-out` legt sie unter POSIX exklusiv mit Modus 0600 an.

| Option | Zweck |
|---|---|
| `--db` | Vorhandene Datenbank |
| `--config` | Aufgelöste Konfiguration |
| `--user` | Konfigurierter Benutzer, im Mehrbenutzerbetrieb erforderlich |
| `--mapping` | Explizite alte/neue JSON-Zuordnungen; Vorschaumodus |
| `--plan-out` | Neue private Plandatei anlegen; nie überschreiben |
| `--apply-plan` | Zuvor geprüften Plan anwenden |
| `--ack-plan` | Exakter Hash des geprüften Plans |
| `--acknowledge-unverified-identity` | Explizite Bekräftigung trotz unbekannter Originalbytes |
