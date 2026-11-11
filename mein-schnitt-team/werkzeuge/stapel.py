#!/usr/bin/env python3
"""Stapelbetrieb: mehrere Videos parallel durch die ganze Kette schicken.

Aufruf:
  python3 werkzeuge/stapel.py <name>=<quelle> [<name>=<quelle> ...] [--parallel 2] [--ab SCHRITT] [--bis SCHRITT]

<quelle> ist ein lokaler Pfad oder drive:<DATEI-ID> (Datei muss per Link freigegeben sein).
Für schon angelegte Videos reicht der Name allein: python3 werkzeuge/stapel.py img6558 --ab untertitel

Schritte (Reihenfolge): laden, takes, schnitt, untertitel, vorschau, export
  laden      Rohvideo holen, videos/<name>/ anlegen, Original schreibschützen
  takes      transkribieren + Take-Finder (Skript-Modus, wenn videos/<name>/skript.txt existiert, sonst frei)
  schnitt    Cutter mit den Regeln aus CLAUDE.md (Pausen 0,10 s, Tempo 1,05x, HDR->SDR)
  untertitel Schnitt neu transkribieren, HyperFrames-Projekt bauen (Skript/Titel, falls vorhanden), check
  vorschau   Entwurfs-Render -> videos/<name>/vorschau/vorschau.mp4 (+ Standbilder)
  export     NUR nach OK des Nutzers: voller Render + Upload-Version (_social.mp4, -14 LUFS)
Standard: --ab laden --bis vorschau. Der Export muss ausdrücklich mit --ab export angefordert werden.

Pro Video optional:
  videos/<name>/skript.txt   bereinigtes Skript (*Sternchen* = Betonung)
  videos/<name>/titel.txt    Hook-Titel (eine Zeile)
  videos/<name>/broll-plan.json
  videos/<name>/einstellungen.json  z. B. {"unten": 400, "farbe": "#D8C09A", "tempo": 1.05, "pause": 0.10}
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HIER = Path(__file__).resolve().parent.parent
W = HIER / "werkzeuge"
SCHRITTE = ["laden", "takes", "schnitt", "untertitel", "vorschau", "export"]
STANDARD = {"pause": 0.10, "tempo": 1.05, "unten": 400, "farbe": "#D8C09A", "modell": "small"}


class Fehler(Exception):
    pass


def lauf(cmd, log, **kw):
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n")
        f.flush()
        r = subprocess.run([str(c) for c in cmd], stdout=f, stderr=subprocess.STDOUT, cwd=HIER, **kw)
    if r.returncode != 0:
        raise Fehler(f"Befehl fehlgeschlagen ({r.returncode}): {cmd[0]} … – Details in {log}")


def rohdatei(v):
    dateien = sorted(p for p in (v / "roh").iterdir() if p.is_file())
    if not dateien:
        raise Fehler("keine Rohdatei in roh/")
    if len(dateien) > 1:
        raise Fehler("mehrere Rohdateien – bitte zuerst zu arbeit/roh-gesamt.mp4 zusammenfügen (siehe Cutter)")
    return dateien[0]


def laden(name, quelle, v, log):
    if (v / "roh").exists() and any((v / "roh").iterdir()):
        return "schon da"
    if not quelle:
        raise Fehler("keine Quelle angegeben")
    tmp = HIER / ".download"
    tmp.mkdir(exist_ok=True)
    if quelle.startswith("drive:"):
        fid = quelle[6:]
        ziel = tmp / f"{name}.mov"
        url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
        lauf(["curl", "-sS", "-L", "--fail", "-o", ziel, url], log)
        with open(ziel, "rb") as f:
            kopf = f.read(64)
        if b"<html" in kopf.lower() or b"<!doctype" in kopf.lower():
            ziel.unlink()
            raise Fehler("Drive liefert eine Login-Seite – Datei ist nicht per Link freigegeben")
        name_drive = drive_dateiname(fid) or ziel.name
        endziel = tmp / name_drive
        ziel.rename(endziel)
        quelle_pfad = endziel
    else:
        quelle_pfad = Path(quelle).resolve()
    lauf([W / "neues-video.sh", name, quelle_pfad], log)
    if quelle.startswith("drive:"):
        quelle_pfad.unlink()
    return "geladen"


def drive_dateiname(fid):
    """Originalnamen aus dem Content-Disposition-Header holen (ohne Download)."""
    try:
        req = urllib.request.Request(
            f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
            method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            cd = r.headers.get("Content-Disposition", "")
        if 'filename="' in cd:
            return cd.split('filename="')[1].split('"')[0]
    except Exception:
        pass
    return None


def einstellungen(v):
    e = dict(STANDARD)
    f = v / "einstellungen.json"
    if f.exists():
        e.update(json.loads(f.read_text(encoding="utf-8")))
    return e


def bearbeite(name, quelle, ab, bis):
    v = HIER / "videos" / name
    v.mkdir(parents=True, exist_ok=True)
    log = v / "stapel.log"
    a = v / "arbeit"
    info = {"name": name, "status": "ok", "schritte": [], "start": time.time()}
    try:
        for schritt in SCHRITTE[SCHRITTE.index(ab):SCHRITTE.index(bis) + 1]:
            e = einstellungen(v)
            skript = v / "skript.txt"
            titel = v / "titel.txt"
            if schritt == "laden":
                info["schritte"].append(f"laden: {laden(name, quelle, v, log)}")
            elif schritt == "takes":
                roh = rohdatei(v)
                lauf([W / "transkribieren.sh", roh, a / "transcript.json", e["modell"]], log)
                cmd = ["python3", W / "takes.py", a / "transcript.json", a / "takes.json"]
                if skript.exists():
                    cmd += ["--skript", skript]
                lauf(cmd, log)
                info["schritte"].append("takes: " + ("Skript-Modus" if skript.exists() else "frei"))
            elif schritt == "schnitt":
                lauf(["python3", W / "schneiden.py", rohdatei(v), a / "takes.json", a / "schnitt.mp4",
                      "--pause", e["pause"], "--tempo", e["tempo"]], log)
                s = json.loads((a / "schnitt.json").read_text(encoding="utf-8"))
                info["dauer"] = f"{s['original_dauer']:.1f}s → {s['schnitt_dauer']:.1f}s"
                info["restpausen"] = len(s["restpausen"])
                info["schritte"].append(f"schnitt: {info['dauer']}, {s['schnitte']} Schnitte")
            elif schritt == "untertitel":
                lauf([W / "transkribieren.sh", a / "schnitt.mp4", a / "schnitt-transcript.json", e["modell"]], log)
                cmd = ["python3", W / "untertitel.py", a / "schnitt.mp4", a / "schnitt-transcript.json", v / "hf",
                       "--unten", e["unten"], "--farbe", e["farbe"]]
                if skript.exists():
                    cmd += ["--skript", skript]
                if titel.exists() and titel.read_text(encoding="utf-8").strip():
                    cmd += ["--titel", titel.read_text(encoding="utf-8").strip()]
                if (v / "broll-plan.json").exists():
                    cmd += ["--broll-plan", v / "broll-plan.json"]
                lauf(cmd, log)
                lauf([W / "hf", "check", v / "hf"], log)
                info["schritte"].append("untertitel: ok" + (" (mit Skript)" if skript.exists() else " (ohne Skript)"))
            elif schritt == "vorschau":
                (v / "vorschau").mkdir(exist_ok=True)
                lauf([W / "hf", "render", v / "hf", "--quality", "draft", "--output",
                      v / "vorschau" / "vorschau.mp4", "--quiet"], log)
                lauf([W / "hf", "snapshot", v / "hf", "--frames", "6", "--output", v / "vorschau" / "bilder"], log)
                info["vorschau"] = str(v / "vorschau" / "vorschau.mp4")
                info["schritte"].append("vorschau: fertig")
            elif schritt == "export":
                ex = v / "export"
                ex.mkdir(exist_ok=True)
                voll = ex / f"{name}.mp4"
                lauf([W / "hf", "render", v / "hf", "--quality", "delivery", "--output", voll, "--quiet"], log)
                lauf(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voll, "-c:v", "libx264",
                      "-preset", "slow", "-crf", "17", "-maxrate", "16M", "-bufsize", "32M", "-pix_fmt", "yuv420p",
                      "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                      "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000", "-c:a", "aac", "-b:a", "192k",
                      "-movflags", "+faststart", ex / f"{name}_social.mp4"], log)
                info["export"] = str(ex / f"{name}_social.mp4")
                info["schritte"].append("export: fertig")
    except Fehler as f:
        info["status"] = f"FEHLER: {f}"
    except Exception as f:  # noqa: BLE001
        info["status"] = f"FEHLER: {type(f).__name__}: {f}"
    info["zeit"] = f"{time.time() - info.pop('start'):.0f}s"
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", help="name=quelle oder nur name")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--ab", default="laden", choices=SCHRITTE)
    ap.add_argument("--bis", default="vorschau", choices=SCHRITTE)
    a = ap.parse_args()
    if a.ab == "export" or a.bis == "export":
        if a.ab != "export":
            sys.exit("Export nur einzeln nach OK des Nutzers: --ab export --bis export")
    if SCHRITTE.index(a.ab) > SCHRITTE.index(a.bis):
        sys.exit("--ab liegt hinter --bis")
    jobs = []
    for eintrag in a.videos:
        name, _, quelle = eintrag.partition("=")
        jobs.append((name.strip(), quelle.strip()))
    print(f"Stapel: {len(jobs)} Video(s), Schritte {a.ab} → {a.bis}, {a.parallel} parallel")
    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        ergebnisse = list(pool.map(lambda j: bearbeite(j[0], j[1], a.ab, a.bis), jobs))
    print("\nErgebnis:")
    for r in ergebnisse:
        print(f"\n■ {r['name']}  [{r['status']}]  ({r['zeit']})")
        for s in r["schritte"]:
            print(f"   - {s}")
        for k in ("restpausen", "vorschau", "export"):
            if k in r:
                print(f"   {k}: {r[k]}")
    (HIER / "videos" / "stapel-ergebnis.json").write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    sys.exit(0 if all(r["status"] == "ok" for r in ergebnisse) else 1)


if __name__ == "__main__":
    main()
