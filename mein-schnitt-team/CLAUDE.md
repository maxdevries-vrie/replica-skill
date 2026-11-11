# Mein Schnitt-Team

Wir sind ein Video-Schnitt-Team. Rohaufnahme + Skript rein, fertig geschnittenes Video mit Untertiteln raus.
**Sprache: immer Deutsch** (mit dem Nutzer, in Dateien, in Untertiteln).

## Feste Regeln (Antworten des Nutzers – gelten für jedes Video)

| Thema | Regel |
| --- | --- |
| Videoart | Gesicht in die Kamera (Talking Head / Face-Cam) |
| Plattform & Format | TikTok und Instagram Reels, **9:16 Hochformat, 1080×1920, 30 fps** |
| Sprechweise | **Nach Skript mit mehreren Takes, aber auch frei.** Liegt ein Skript bei → Skript-Modus (bester Take pro Satz). Fehlt es oder wird frei gesprochen → Frei-Modus (abgebrochene Anläufe und Wiederholungen erkennen). Gemischt ist erlaubt: freie Einschübe, die im Skript fehlen, nicht automatisch löschen, sondern dem Nutzer zeigen. |
| Schnitt-Stil | **Schnell und knackig.** Pausen auf **0,10 s** kürzen (`--pause 0.10`), Tempo **1,05×** (`--tempo 1.05`, Tonhöhe bleibt), Versprecher, Füllwörter (äh, ähm …) und doppelte Anläufe raus. Jeder zweite Schnitt bekommt einen leichten Punch-in (108 %), damit Jump-Cuts gewollt wirken. Ton auf −14 LUFS. |
| Untertitel | **Immer an.** **Kurze Zeilen mit 2–4 Wörtern (max. ~20 Zeichen), die als Ganzes erscheinen, nicht Wort für Wort.** Weiß, Montserrat 900, schwarze Kontur, **tief auf Brusthöhe: `--unten 400`** (tiefer verdeckt die TikTok/Instagram-Oberfläche), nie im Gesicht. Kurzer Pop beim Einblenden. Mit `*Sternchen*` markierte Skriptwörter werden **beige (#D8C09A, passend zum Kanzlei-Logo)** hervorgehoben (`--farbe "#D8C09A"`). Beträge (z. B. *300 €*) und Kommentar-Stichwörter immer betonen. |
| Grafik | Hook-Titel oben in den ersten ~2,6 s: beige Box (#D8C09A), dunkelbraune Schrift, kurz und provokant (Beispiel: „Gehaltserhöhung? Nicht so!“). Dem Nutzer 3 Varianten vorschlagen, er entscheidet. Hook und Grafiken bleiben im Bereich 168–1330 px (TikTok/Instagram-Oberfläche); einzige gewollte Ausnahme sind die Untertitel auf Brusthöhe (bis ca. 1520 px). B-Roll aus einem Ordner, den der Nutzer angibt, an passenden Stellen vollflächig einblenden (Bilder mit leichtem Zoom). |

## Unverhandelbar

- **Originale werden nie verändert.** `videos/<name>/roh/` ist nur zum Lesen da (Dateien sind schreibgeschützt). Alles Neue landet in `arbeit/`, `hf/`, `vorschau/`, `export/`.
- **Transkription nur lokal und nur mehrsprachig:** `werkzeuge/transkribieren.sh` (Whisper `small`, `--language de`). **Nie ein `.en`-Modell**, das übersetzt Deutsch ins Englische. Bei schlechter Qualität `medium` nehmen.
- **Pausen immer zusätzlich mit ffmpeg silencedetect messen**, weil Wort-Zeitstempel an Pausen ungenau sind. Den fertigen Schnitt danach noch einmal prüfen (macht `schneiden.py` automatisch, Ergebnis unter `restpausen`).
- **Erst Vorschau, dann Export.** Der finale Export (`--quality delivery`) wird erst gerendert, wenn der Nutzer die Vorschau freigegeben hat.

## Das Team (`.claude/agents/`)

1. **take-finder**: vergleicht Transkript und Skript und wählt pro Satz den besten Take → `arbeit/takes.json`
2. **cutter**: schneidet, kürzt Pausen (silencedetect), prüft den Schnitt → `arbeit/schnitt.mp4`
3. **untertitel-grafik**: transkribiert den Schnitt neu, gleicht mit dem Skript ab, baut Untertitel, Hook-Titel und B-Roll in HyperFrames → `hf/`, `vorschau/`

Sind die Agenten in einer Sitzung nicht aufrufbar, übernimmt Claude ihre Rollen selbst in derselben Reihenfolge.

## Ablauf pro Video

```bash
werkzeuge/neues-video.sh <name> <rohaufnahme.mp4> [skript.txt] [broll-ordner]   # legt videos/<name>/ an
# 1 Take-Finder
werkzeuge/transkribieren.sh videos/<name>/roh/<datei> videos/<name>/arbeit/transcript.json
python3 werkzeuge/takes.py videos/<name>/arbeit/transcript.json videos/<name>/arbeit/takes.json [--skript videos/<name>/skript.txt]
# 2 Cutter
python3 werkzeuge/schneiden.py videos/<name>/roh/<datei> videos/<name>/arbeit/takes.json videos/<name>/arbeit/schnitt.mp4 --pause 0.10 --tempo 1.05
# 3 Untertitel & Grafik
werkzeuge/transkribieren.sh videos/<name>/arbeit/schnitt.mp4 videos/<name>/arbeit/schnitt-transcript.json
python3 werkzeuge/untertitel.py videos/<name>/arbeit/schnitt.mp4 videos/<name>/arbeit/schnitt-transcript.json videos/<name>/hf \
  --unten 400 --farbe "#D8C09A" [--skript videos/<name>/skript.txt] [--titel "Hook"] [--broll-plan videos/<name>/arbeit/broll-plan.json]
werkzeuge/hf check "$PWD/videos/<name>/hf"
werkzeuge/hf render "$PWD/videos/<name>/hf" --quality draft --output "$PWD/videos/<name>/vorschau/vorschau.mp4"
# Nach OK des Nutzers:
werkzeuge/hf render "$PWD/videos/<name>/hf" --quality delivery --output "$PWD/videos/<name>/export/<name>.mp4"
# Upload-Version für TikTok/Instagram (kleiner, -14 LUFS) – diese Datei an den Nutzer schicken:
ffmpeg -i export/<name>.mp4 -c:v libx264 -preset slow -crf 17 -maxrate 16M -bufsize 32M -pix_fmt yuv420p \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11" -c:a aac -b:a 192k -movflags +faststart export/<name>_social.mp4
```

## Stapelbetrieb (mehrere Videos auf einmal)

```bash
# 1) Laden + Transkript + Takes für alle (parallel):
python3 werkzeuge/stapel.py img6558=drive:<ID> img6538=drive:<ID> --bis takes
# 2) Pro Video: Transkript lesen, bereinigtes skript.txt schreiben, doppelte Formulierungen ggf. in
#    arbeit/takes.json heraustrennen (Grenzen per silencedetect), 3 Hooks überlegen -> bester in titel.txt
# 3) Schnitt + Untertitel + Vorschau für alle:
python3 werkzeuge/stapel.py img6558 img6538 --ab schnitt --bis vorschau
# 4) Feedback einarbeiten (z. B. nur Untertitel neu): --ab untertitel --bis vorschau
# 5) Nach OK des Nutzers, nur für freigegebene Videos:
python3 werkzeuge/stapel.py img6558 --ab export --bis export
```

- Quelle `drive:<ID>`: Datei-ID aus Google Drive (Drive-Connector `search_files`), Datei muss per Link freigegeben sein.
- Abweichungen pro Video in `videos/<name>/einstellungen.json` (`unten`, `farbe`, `tempo`, `pause`, `modell`).
- Protokoll pro Video: `videos/<name>/stapel.log`; Gesamtergebnis: `videos/stapel-ergebnis.json`.
- Läuft länger als 10 Minuten: im Hintergrund starten.

## Technische Hinweise

- HyperFrames-CLI immer über `werkzeuge/hf` aufrufen (nutzt die Plugin-Version, setzt den Proxy für Node). Projektpfade **absolut** übergeben, weil der Launcher aus dem Home-Ordner startet.
- GSAP liegt lokal in `vorlagen/gsap.min.js` (CDN ist in der Cloud-Umgebung gesperrt). `untertitel.py` kopiert es ins Projekt.
- Vor jeder Änderung an einem bestehenden `hf/`-Projekt: `werkzeuge/hf timeline "$PWD/videos/<name>/hf" --json` lesen. Handänderungen des Nutzers nicht überschreiben. Wird `untertitel.py` neu ausgeführt, vorher fragen.
- Mehrere Rohdateien: zuerst in Aufnahmereihenfolge zu `arbeit/roh-gesamt.mp4` zusammenfügen (neu encodieren) und damit weiterarbeiten. Die Originale bleiben unberührt.
- Der Testclip unter `test/` ist die Referenz, ob die Kette funktioniert.
- **iPhone-Aufnahmen sind HDR (HLG).** `schneiden.py` erkennt das und rechnet nach SDR um (`--npl 100` ist abgestimmt; höher = dunkler).
- Untertitel-Höhe pro Video an das Gesicht anpassen: `untertitel.py --unten <px>` (Nutzer-Standard 400 = Brusthöhe). Immer per Snapshot prüfen.
- Ohne Skript: aus dem Transkript ein bereinigtes `skript.txt` schreiben (Satzzeichen, „€“ statt „Euro“, Beträge und Schlüsselwörter in *Sternchen*). Unsichere Wörter mit `medium` gegenprüfen und dem Nutzer zeigen. Das Skript gilt dann als Wahrheit für den Untertiteltext.
- Rohvideos aus Google Drive: Der Connector lädt nur bis 10 MB. Größere Dateien stellt der Nutzer kurz auf „Jeder mit dem Link“, dann `curl -L "https://drive.usercontent.google.com/download?id=<ID>&export=download&confirm=t"`. Danach daran erinnern, die Freigabe zurückzusetzen.
