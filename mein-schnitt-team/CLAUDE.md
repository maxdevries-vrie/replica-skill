# Mein Schnitt-Team

Wir sind ein Video-Schnitt-Team. Rohaufnahme + Skript rein, fertig geschnittenes Video mit Untertiteln raus.
**Sprache: immer Deutsch** (mit dem Nutzer, in Dateien, in Untertiteln).

## Feste Regeln (Antworten des Nutzers – gelten für jedes Video)

| Thema | Regel |
| --- | --- |
| Videoart | Gesicht in die Kamera (Talking Head / Face-Cam) |
| Plattform & Format | TikTok und Instagram Reels, **9:16 Hochformat, 1080×1920, 30 fps** |
| Sprechweise | **Nach Skript mit mehreren Takes, aber auch frei.** Liegt ein Skript bei → Skript-Modus (bester Take pro Satz). Fehlt es oder wird frei gesprochen → Frei-Modus (abgebrochene Anläufe und Wiederholungen erkennen). Gemischt ist erlaubt: freie Einschübe, die im Skript fehlen, nicht automatisch löschen, sondern dem Nutzer zeigen. |
| Schnitt-Stil | **Schnell und knackig.** Pausen auf **0,15 s** kürzen, Versprecher, Füllwörter (äh, ähm …) und doppelte Anläufe raus. Jeder zweite Schnitt bekommt einen leichten Punch-in (108 %), damit Jump-Cuts gewollt wirken. Ton auf −14 LUFS. |
| Untertitel | **Immer an.** **Kurze Zeilen mit 2–4 Wörtern (max. ~20 Zeichen), die als Ganzes erscheinen, nicht Wort für Wort.** Weiß, Montserrat 900, schwarze Kontur, etwa 640 px über dem unteren Rand (über der App-Oberfläche, nicht im Gesicht). Kurzer Pop beim Einblenden. Mit `*Sternchen*` markierte Skriptwörter werden gelb (#FFD60A) hervorgehoben. |
| Grafik | Optional ein Hook-Titel oben in den ersten ~2,6 s (gelbe Box). Alles Lesbare bleibt im Bereich 168–1330 px (TikTok/Instagram-Oberfläche). B-Roll aus einem Ordner, den der Nutzer angibt, an passenden Stellen vollflächig einblenden (Bilder mit leichtem Zoom). |

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
python3 werkzeuge/schneiden.py videos/<name>/roh/<datei> videos/<name>/arbeit/takes.json videos/<name>/arbeit/schnitt.mp4
# 3 Untertitel & Grafik
werkzeuge/transkribieren.sh videos/<name>/arbeit/schnitt.mp4 videos/<name>/arbeit/schnitt-transcript.json
python3 werkzeuge/untertitel.py videos/<name>/arbeit/schnitt.mp4 videos/<name>/arbeit/schnitt-transcript.json videos/<name>/hf \
  [--skript videos/<name>/skript.txt] [--titel "Hook"] [--broll-plan videos/<name>/arbeit/broll-plan.json]
werkzeuge/hf check "$PWD/videos/<name>/hf"
werkzeuge/hf render "$PWD/videos/<name>/hf" --quality draft --output "$PWD/videos/<name>/vorschau/vorschau.mp4"
# Nach OK des Nutzers:
werkzeuge/hf render "$PWD/videos/<name>/hf" --quality delivery --output "$PWD/videos/<name>/export/<name>.mp4"
```

## Technische Hinweise

- HyperFrames-CLI immer über `werkzeuge/hf` aufrufen (nutzt die Plugin-Version, setzt den Proxy für Node). Projektpfade **absolut** übergeben, weil der Launcher aus dem Home-Ordner startet.
- GSAP liegt lokal in `vorlagen/gsap.min.js` (CDN ist in der Cloud-Umgebung gesperrt). `untertitel.py` kopiert es ins Projekt.
- Vor jeder Änderung an einem bestehenden `hf/`-Projekt: `werkzeuge/hf timeline "$PWD/videos/<name>/hf" --json` lesen. Handänderungen des Nutzers nicht überschreiben. Wird `untertitel.py` neu ausgeführt, vorher fragen.
- Mehrere Rohdateien: zuerst in Aufnahmereihenfolge zu `arbeit/roh-gesamt.mp4` zusammenfügen (neu encodieren) und damit weiterarbeiten. Die Originale bleiben unberührt.
- Der Testclip unter `test/` ist die Referenz, ob die Kette funktioniert.
