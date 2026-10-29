# Erste Schritte

> 🌐 [English](../GETTING_STARTED.md) · [Français](../fr/GETTING_STARTED.md) · **Deutsch** · [Italiano](../it/GETTING_STARTED.md) · [Español](../es/GETTING_STARTED.md) · [Português](../pt/GETTING_STARTED.md) · [简体中文](../zh/GETTING_STARTED.md)

Sie haben einen frischen Stapel Fotos und möchten eine kuratierte Auswahl. Diese Seite führt
durch sechs Schritte — importieren, Ähnliches gruppieren, Facet Ihren Geschmack beibringen,
aussortieren, verschlagworten, exportieren — und verweist für die Details jeweils weiter.

![Facet-Galerie im Überblick](../screenshots/walkthrough.gif)

## Bevor Sie beginnen

### 1. Ein Bearbeitungspasswort festlegen

Eine frische Installation ist **schreibgeschützt**. Um etwas zu ändern (Bewertungen, Aussortieren,
Gesichter, Alben, Tags, Scan), setzen Sie `viewer.edition_password` in `scoring_config.json` und
starten Sie den Viewer neu (die Konfiguration wird nicht im laufenden Betrieb neu geladen).

Mit der mitgelieferten `docker-compose.yml` erzeugt das Image beim ersten Start ein Passwort und
gibt es einmal aus:

```bash
docker compose logs facet
```

Melden Sie sich anschließend in der Galerie als Editor an. Details: [Einzelbenutzermodus](VIEWER.md#einzelbenutzermodus-standard) und [Docker-Einstellungen, die Sie ändern können](INSTALLATION.md#docker-einstellungen-die-sie-ändern-können).

![Bearbeitungs-Anmeldung](../screenshots/getting-started-edition-login.jpg)

### 2. Einen Installationsweg wählen

Docker ist der kürzeste Weg unter Windows, macOS und Linux; eine native Installation ist für
alle, die auf Container verzichten möchten. [Welche Installation passt zu mir?](INSTALLATION.md#welche-installation-passt-zu-mir)
enthält die Tabelle.

Zwei Dinge bereiten bei Containern häufig Probleme:

- **Konfiguration und Dateibesitz.** Der Container läuft als uid 1000, die rootloses Podman
  auf eine Host-Subuid abbildet, sodass von ihm in `./facet-config` erzeugte Dateien
  möglicherweise nicht Ihrem Benutzer gehören. Siehe
  [Dateibesitz im Container](INSTALLATION.md#dateibesitz-im-container).
- **Pfade sind die des Containers, nicht die des Hosts.** Sie scannen `/data/photos`, nicht
  `~/Pictures`. Siehe [Pfadsemantik im Container](DEPLOYMENT.md#pfadsemantik-im-container).

### 3. Keine GPU? Kein Problem

Alles funktioniert mit dem CPU-Profil `legacy`, nur langsamer. Siehe
[Keine Grafikkarte](INSTALLATION.md#keine-grafikkarte) und
[Welches Profil passt zu meiner Hardware?](INSTALLATION.md#welches-profil-passt-zu-meiner-hardware).

### 4. Auf den Speicher achten

Ein Container mit Speicherlimit kann bei den größeren Profilen mitten im Scan beendet werden.
Prüfen Sie [Speicherlimits für Container](DEPLOYMENT.md#speicherlimits-für-container), bevor Sie eines setzen; auf
einem Mac siehe [Speicher auf einem Mac](INSTALLATION.md#speicher-auf-einem-mac).

## Der Ablauf

### Schritt 1: Bilder importieren

Legen Sie Ihre Fotos in den Ordner, auf den Facet zeigt (JPEG, HEIF/HEIC, PNG und die
gängigen RAW-Formate — siehe [unterstützte Dateitypen](README.md#unterstützte-dateitypen)),
und scannen Sie ihn. Das geht im Terminal ([Scannen](COMMANDS.md#scannen)) oder im Browser:

- Setzen Sie `viewer.features.show_scan_button` auf `true` (standardmäßig aus).
- Einzelbenutzer: Sie benötigen ein Bearbeitungspasswort **und** müssen als Editor angemeldet
  sein. Mehrbenutzer: Sie benötigen die Rolle Superadmin.
- Fügen Sie den Ordner zu `viewer.scan_directories` hinzu, damit der Starter etwas zur Auswahl hat.

Eine Schaltfläche **Neue Fotos scannen** erscheint dann am Ende der Kopfzeile (auf kleinen
Bildschirmen in der unteren Leiste). Siehe [Scan auslösen](VIEWER.md#scan-auslösen). Der erste Scan lädt die KI-Modelle
einmalig herunter ([Erster Start](INSTALLATION.md#erster-start-was-sie-erwartet)).

![Scan-Schaltfläche am Ende der Kopfleiste](../screenshots/getting-started-scan-button.jpg)

### Schritt 2: Duplikate, Serienbilder und Ähnliches finden

Facet gruppiert Serienbildaufnahmen, Beinahe-Duplikate, Belichtungsreihen und Panoramen von
selbst, und die Galerie **blendet standardmäßig den Großteil einer Gruppe aus**, sodass Sie
einen Vertreter sehen. Wenn Ihre Fotoanzahl niedriger aussieht als erwartet, liegt das an den
Ausblend-Schaltern, nicht an fehlenden Dateien — siehe
[Anzeigeoptionen](VIEWER.md#anzeigeoptionen) und [Standardfilter](VIEWER.md#standardfilter).
Um eine ganze Gruppe nebeneinander zu sehen, öffnen Sie [Ähnliche Fotos](VIEWER.md#ähnliche-fotos) oder die
[Auswahl](VIEWER.md#auswahl)-Dunkelkammer; Gruppen, die ganz bleiben müssen, sind unter
[Panoramen und Belichtungsreihen](VIEWER.md#panoramen-und-belichtungsreihen) beschrieben.

![Serienbild-Auswahl](../screenshots/burst-culling.jpg)

### Schritt 3: Facet zeigen, welches Sie bevorzugen

Jede Wahl, die Sie beim Aussortieren treffen, und jede A/B-Entscheidung im Vergleichsmodus
ist ein Signal. Facet lernt daraus ein persönliches Ranking und stellt es als **Mein Geschmack**
bereit ([Mein Geschmack](VIEWER.md#mein-geschmack)). Wählen Sie „dieses schlägt jenes" im
[Paarweisen Vergleichsmodus](VIEWER.md#paarweiser-vergleichsmodus) oder sortieren Sie einfach aus — die
[Auswahl](VIEWER.md#auswahl)-Ansicht erfasst Ihre Behalten- und Ablehnen-Entscheidungen. Der Ranker trainiert
nach genügend neuen Entscheidungen von selbst nach, und zwar erst, wenn Sie pausieren
([Automatisches Nachtrainieren](CONFIGURATION.md#automatisches-nachtrainieren)).

![Zwei Fotos vergleichen](../screenshots/getting-started-teach.jpg)

### Schritt 4: Verwerfen, was Sie nicht wollen

Lehnen Sie Fotos beim Aussortieren ab oder wählen Sie eine Gruppe aus und wenden Sie eine
Aktion darauf an
([Mehrfachauswahl & Sammelaktionen](VIEWER.md#mehrfachauswahl--sammelaktionen)):
[Top N% behalten](VIEWER.md#top-n-behalten), [In Ordner aussortieren](VIEWER.md#in-ordner-aussortieren) oder
[Löschen](VIEWER.md#löschen).

- **In Ordner aussortieren** zeigt eine Trockenlauf-Vorschau, bis Sie es anwenden.
- **Löschen** verschiebt Dateien in den Papierkorb des Betriebssystems, und nur wenn `viewer.cull.allow_trash` aktiviert ist (standardmäßig aus).
- **[Rückgängig](VIEWER.md#rückgängig)** deckt Flag-Änderungen und Bestätigungen beim Aussortieren ab, nicht Dateiverschiebungen oder Löschvorgänge.
- **Ziele** sind auf Ihre Scan-Verzeichnisse plus `viewer.export.allowed_target_dirs` beschränkt
  ([Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung)).

Um im Terminal auszusortieren:
[Eine Aufnahmesession im Terminal aussortieren](COMMANDS.md#eine-aufnahmesession-im-terminal-aussortieren).

Fotos, die Sie außerhalb von Facet löschen, hinterlassen ihre Datenbankzeile, bis Sie die
Bereinigung unter [Datenbankpflege](COMMANDS.md#datenbankpflege) ausführen.

![Sammelaktionen auf einer Auswahl](../screenshots/getting-started-discard.jpg)

### Schritt 5: Tags und Metadaten zu den behaltenen Fotos hinzufügen

Facet verschlagwortet Fotos automatisch. Fügen Sie **eigene Tags** in der Foto-Detailansicht
oder über die Sammelaktionen hinzu. Manuelle Tags überstehen erneutes Scannen, funktionieren
in Filtern und der Suche und sind in Freigabelinks verborgen. Siehe
[Manuelle Tags](VIEWER.md#manuelle-tags) und
[Manuelle Tags und XMP-Stichwörter](INTEROP.md#manuelle-tags-und-xmp-stichwörter). Um Bewertungen
und Stichwörter nach Lightroom, Capture One, digiKam oder darktable mitzunehmen, siehe [Interop](INTEROP.md)
(dafür wird zum Einbetten [exiftool](INSTALLATION.md#exiftool) benötigt).

![Manuelle Tags in der Detailansicht](../screenshots/getting-started-manual-tags.jpg)

### Schritt 6: Die kuratierte Auswahl exportieren

Legen Sie Ihre behaltenen Fotos in ein Album und exportieren Sie von dort, oder nutzen Sie
den [Editor-Export](VIEWER.md#editor-export) für die Übergabe an einen Editor, oder
[In Ordner aussortieren](VIEWER.md#in-ordner-aussortieren), um die behaltenen Fotos in einen Ordner zu kopieren. Es gilt
dieselbe Positivliste für Ziele wie in Schritt 4
([Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung)).

![Export an einen Editor](../screenshots/getting-started-export.jpg)

## Wie es weitergeht

[Viewer](VIEWER.md) für jede Galeriefunktion, [Befehle](COMMANDS.md) für das Terminal,
[Bewertung](SCORING.md), um anzupassen, was als gutes Foto zählt, und
[Bereitstellung](DEPLOYMENT.md) für ein NAS oder einen gemeinsam genutzten Server.
