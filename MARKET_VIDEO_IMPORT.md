# Marktvideo-Import – vorbereitet, noch nicht aktiviert

Erst nach Abschluss des Tom-Vorwald-Imports einsetzen. Die neue Datei verwendet die vorhandene `channels.json`. Sie verändert weder `video_scanner.py` noch dessen Merkliste, Discord-Versand, Zeitplan oder den X-Scraper.

## Festgelegte Auswahl

- Beim ersten erfolgreichen Scan pro Kanal: höchstens die drei neuesten geeigneten Videos, maximal 14 Kalendertage alt (UTC-Datum, einschließlich Grenztag).
- Ältere geeignete Treffer desselben Erstscans werden als `baseline` vermerkt und später nicht nachträglich importiert.
- Danach: neu entdeckte Videos innerhalb dieser Altersgrenze. Die drei sind eine Startbegrenzung, keine dauerhafte Grenze.
- Es wird nur der Bereich `/videos` betrachtet. Shorts, laufende/geplante Streams und Videos bis einschließlich drei Minuten werden zusätzlich ausgeschlossen. Dadurch entfallen vorsichtshalber auch kurze normale Videos.
- Unbekanntes Veröffentlichungsdatum wird nicht als „neu“ gewertet. Erst nach vollständig erfolgreicher Metadatenprüfung wird ein Kanal initialisiert.
- Pro Durchlauf werden höchstens zehn Untertitel abgerufen, insgesamt über alle Kanäle. Bei elf Kanälen können beim ersten Scan bis zu 33 Videos in der Warteschlange entstehen.

## Manuell verwenden (Linux, Colab oder macOS; Python 3.11+)

Im Repository-Verzeichnis, in einer eigenen Python-Umgebung:

```bash
python -m pip install -r requirements-market-import.txt
python market_video_import.py
```

Dies sammelt nur Metadaten und eine Warteschlange. Untertitel werden ausdrücklich zugeschaltet:

```bash
python market_video_import.py --transcribe
```

Die Dateien entstehen unter `market_video_import/`:

- `state.json`: dauerhafte Merkliste; nicht leeren oder bei jedem Colab-Neustart verlieren.
- `pending_links.txt`: offene URLs, auch zur späteren Audio-Transkription geeignet.
- `last_run.json`: Mengen, Einstellungen und Fehler des letzten Laufs.
- `vault/02_Trading/Briefings/Rohmaterial/<Video-ID>.md`: vollständige verfügbare deutsche oder englische Untertitel mit Zeitmarken und Quellenangaben.

In Colab muss `--output` auf einen dauerhaft gespeicherten Ordner zeigen, beispielsweise in einem zuvor eingebundenen Google Drive. Sonst gehen Merkliste und Ergebnisse beim Laufzeitende verloren. Es dürfen keine zwei getrennten Kopien derselben Merkliste gleichzeitig weitergeführt werden.

Bereits im Second Brain gespeicherte Tom-Videos vor dem ersten Start als JSON-Liste ihrer IDs bereitstellen und bei jedem Lauf angeben:

```bash
python market_video_import.py --known-ids tom_bereits_importiert.json --transcribe
```

Format: `["Coqi3xfqSDA", "nE4pyD105Ys"]` – Beispiel, keine vollständige Bestandsliste. Bekannte Videos werden nicht nochmals exportiert; es wird dafür kein viertes älteres Startvideo nachgezogen. Vor dem späteren Start die vollständige Liste aus dem aktuellen Tom-Bestand erzeugen.

## Grenzen und nächster Schritt

Es werden die letzten 30 Uploads pro Kanal geprüft, bei Bedarf mit einzelnen Metadatenabrufen. Bei sehr vielen Uploads oder langen Pausen können Videos außerhalb dieses Fensters fehlen. Das Fenster lässt sich mit `--window` erhöhen; dies erzeugt zusätzliche YouTube-Anfragen. Ohne Untertitel bleibt ein Video offen. Dieses Werkzeug führt noch keine Audio-/Whisper-Transkription oder KI-Auswertung durch.

Bei erkannten YouTube-Sperren endet der Durchlauf sofort. Andere Abruffehler bleiben für spätere Versuche erhalten und führen ebenfalls zu einem Fehlerstatus des Laufs. Über 14 Tage alte offene Videos werden als `expired` aus der aktiven Warteschlange genommen. Bereits gespeicherte Texte werden nicht gelöscht. Vorhandene Rohdateien werden nicht überschrieben. Ein Lauf mit Fehlern liefert Exitcode 2, ein erfolgreicher Lauf 0.

Die Markdown-Dateien sind ungeprüftes Rohmaterial: Untertitel erfassen keine ausschließlich sichtbaren Chartlevel. Erst danach folgen Quellenprüfung, Auswertung und Briefing. Noch gibt es keinen automatischen Transfer nach GitHub/Obsidian und keinen neuen Zeitplan. Vor Aktivierung einen kleinen echten Durchlauf prüfen, Tom-Dubletten ausschließen und den gewünschten Rhythmus festlegen. LEARNINGS.md und MEMORY.md bleiben unverändert.

Offline-Prüfung:

```bash
python -m unittest discover -s tests -p 'test_market_video_import.py' -v
```
