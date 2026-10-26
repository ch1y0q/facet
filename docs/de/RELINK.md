# Verschobene Fotos neu verknüpfen

`python database.py --relink-photos` ändert nur Datenbankpfade bereits erfasster Fotos nach einem manuellen Verschieben. Viewer, Scanner und externe Editoren vorher stoppen und die Datenbank sichern. Originale und Begleitdateien werden weder verschoben noch geschrieben oder gelöscht; Immich wird nicht aufgerufen.

Anwenden hält Facets Wartungssperre bis zum Ende des Datenbankschreibens. Ein anderer Bibliotheksauftrag führt zu Exitcode 75 ohne Änderungen an Datenbank oder Medien; eine unbenutzbare Sperre zu Exitcode 1. Die Vorschau bleibt schreibgeschützt und nimmt keine Bibliothekssperre. Die Sperre koordiniert Aufträge auf einem Host; die Offline-Anforderungen gelten weiterhin für andere Hosts und externe Editoren.

Die Datenbank beweist nicht die Byte-Identität des fehlenden Originals: Jeder Plan trägt `original_bytes_unknown`. SHA-256 bezeichnet nur die geprüfte neue Zieldatei. Prüfen Sie die Identität unabhängig vor beiden Bestätigungen; eine falsche Zuordnung kann Anmerkungen mit dem falschen Bild verbinden.

Pfade müssen absolut, nativ und kanonisch ohne Symlinks innerhalb konfigurierter Wurzeln sein. Das alte Original muss fehlen, sein lesbarer Elternordner aber existieren. Ganze verschwundene Ordner werden abgelehnt, da der Datenträger offline sein könnte. Keine leeren alten Ordner zur Umgehung anlegen. Ein lesbarer Ordner beweist keinen Mount; `source_mount_status=not_verified` erfordert eigene Prüfung.

Die Vorschau schreibt nichts in die Datenbank. Prüfen Sie den gespeicherten Plan; Anwenden prüft Dateien, Hashes, bekannte Maße, Anmerkungen, Schema, Datenbank-Inode und Zugriff erneut in einer SQLite-Transaktion. Konflikte rollen das ganze Paket zurück. Andere Programme sperrt dies nicht aus. Pläne werden exklusiv mit POSIX0600 angelegt und enthalten private Pfade.

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
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

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

Zeilen-IDs, Bewertung/Keep/GPS, Tags, Gesichter/Personen, manuelle UUIDs, Vergleiche, Einstellungen, feste Alben und Vektoren behalten ihre Beziehungen. Alle manuellen Rechtecke brauchen ausdrückliche Prüfung und Speichern im Editor. Historische Aktionen behalten alte Pfade und sind eventuell nicht mehr rückgängig zu machen; private Revisionen verfallen. Smartalbum-Filter, logische Gruppenschlüssel, historische Protokolle und Immich-Zustand bleiben unverändert.

Begleiter ausdrücklich mit altem/neuem Pfad und `kind` angeben: `sidecar_full` für `photo.ext.xmp`, `sidecar_basename` für `photo.xmp`, `sidecar_facet` für `photo.ext.facet.xmp`, `raw` für ein nicht indexiertes RAW gleichen Stamms. Indexierte RAWs erhalten eigene Haupteinträge; indexiertes RAW/JPEG gemeinsam im selben Plan verknüpfen. Begleiterbytes bleiben unverändert; unbekannte verschwundene Begleiter sind nicht auffindbar.

Mehrbenutzerbetrieb verlangt `--user` und dieselbe Sichtbarkeit aller Benutzer vor/nachher. Leere/unzugängliche Wurzeln und path_mapping sowie vorhandene Originale, erfasste Ziele, doppelte Dateien/Inodes, Groß-/Unicode-/Doppelendungs-Kollisionen, mehrere RAWs, ungenannte Begleiter oder Formatwechsel werden abgelehnt. Grenzen:100 Fotos,300 Dateien,512MiB je Datei,2GiB gesamt,2MiB JSON. Bei Bedarf kleinere Pakete verwenden.
