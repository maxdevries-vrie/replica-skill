#!/usr/bin/env python3
"""Cutter: setzt den Schnitt aus takes.json zusammen.

schneiden.py <original.mp4> <takes.json> <ausgabe.mp4> [--pause 0.15] [--noise -35dB] [--punch 1.08]

- Schnittkanten werden mit ffmpeg silencedetect nachgemessen (Wort-Zeitstempel sind an Pausen ungenau).
- Jede Pause (an Schnitten und innerhalb von Sätzen) wird auf --pause Sekunden gekürzt.
- Jeder zweite Schnitt bekommt einen leichten Punch-in, damit Jump-Cuts gewollt wirken.
- Ausgabe 1080x1920, 30 fps, Ton auf -14 LUFS. Das Original wird nie verändert.
- Danach wird der fertige Schnitt erneut mit silencedetect geprüft (Bericht in <ausgabe>.json).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gemeinsam import dauer, schreibe_json, stille  # noqa: E402

SUCHFENSTER = 0.25  # so weit darf eine Kante zur echten Sprachgrenze rutschen


def verfeinern(segmente, luecken, pause, total):
    vor = pause / 2  # Luft vor dem ersten Laut
    nach = pause - vor  # Luft nach dem letzten Laut
    stuecke = []
    for seg in segmente:
        s, e = seg["start"], seg["ende"]
        for a, b in luecken:
            if a <= s < b or s - SUCHFENSTER <= b <= s:  # Start liegt in Stille / Einsatz kurz davor
                s = b
            if a < e <= b or e <= a <= e + SUCHFENSTER:  # Ende liegt in Stille / Ende kurz danach
                e = a if a > s else e
        if e <= s:
            continue
        # Pausen innerhalb des Segments kürzen
        teile, anfang = [], s
        for a, b in luecken:
            if anfang < a and b < e and (b - a) > pause + 0.05:
                teile.append([anfang, a])
                anfang = b
        teile.append([anfang, e])
        for i, (x, y) in enumerate(teile):
            stuecke.append({"start": max(0.0, x - vor), "ende": min(total, y + nach), "satz": seg.get("satz", "")})
    stuecke.sort(key=lambda p: p["start"])
    zusammen = []
    for p in stuecke:
        if zusammen and p["start"] <= zusammen[-1]["ende"] + 0.02:
            zusammen[-1]["ende"] = max(zusammen[-1]["ende"], p["ende"])
        else:
            zusammen.append(dict(p))
    return zusammen


def filtergraph(stuecke, breite, hoehe, punch, fps, lufs):
    zeilen, va = [], []
    norm = (f"scale={breite}:{hoehe}:force_original_aspect_ratio=increase,"
            f"crop={breite}:{hoehe},setsar=1,fps={fps}")
    for i, p in enumerate(stuecke):
        d = p["ende"] - p["start"]
        v = f"[0:v]trim=start={p['start']:.3f}:end={p['ende']:.3f},setpts=PTS-STARTPTS,{norm}"
        if punch > 1 and i % 2 == 1:
            v += (f",scale=iw*{punch}:ih*{punch},crop={breite}:{hoehe}:(iw-{breite})/2:(ih-{hoehe})*0.35,setsar=1")
        zeilen.append(v + f"[v{i}]")
        f = min(0.012, d / 4)
        zeilen.append(f"[0:a]atrim=start={p['start']:.3f}:end={p['ende']:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d={f:.3f},afade=t=out:st={d - f:.3f}:d={f:.3f}[a{i}]")
        va.append(f"[v{i}][a{i}]")
    zeilen.append("".join(va) + f"concat=n={len(stuecke)}:v=1:a=1[vc][ac]")
    zeilen.append(f"[ac]loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[ao]")
    return ";\n".join(zeilen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("takes")
    ap.add_argument("ausgabe")
    ap.add_argument("--pause", type=float, default=0.15)
    ap.add_argument("--noise", default="-35dB")
    ap.add_argument("--punch", type=float, default=1.08)
    ap.add_argument("--breite", type=int, default=1080)
    ap.add_argument("--hoehe", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--lufs", type=float, default=-14)
    a = ap.parse_args()

    orig = str(Path(a.original).resolve())
    aus = Path(a.ausgabe).resolve()
    if aus == Path(orig):
        sys.exit("Fehler: Ausgabe darf nie das Original überschreiben.")
    aus.parent.mkdir(parents=True, exist_ok=True)

    total = dauer(orig)
    luecken = stille(orig, a.noise, 0.12)
    segmente = json.loads(Path(a.takes).read_text(encoding="utf-8"))["segmente"]
    stuecke = verfeinern(segmente, luecken, a.pause, total)
    if not stuecke:
        sys.exit("Keine Segmente zum Schneiden.")

    graph = aus.with_suffix(".filter.txt")
    graph.write_text(filtergraph(stuecke, a.breite, a.hoehe, a.punch, a.fps, a.lufs), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", orig,
           "-filter_complex_script", str(graph), "-map", "[vc]", "-map", "[ao]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-g", str(a.fps), "-keyint_min", str(a.fps), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(aus)]
    subprocess.run(cmd, check=True)

    # Zeitplan Original -> Schnitt (für Untertitel und B-Roll)
    t = 0.0
    for p in stuecke:
        p["ziel_start"] = round(t, 3)
        t += p["ende"] - p["start"]
        p["ziel_ende"] = round(t, 3)

    # Prüfung des fertigen Schnitts
    rest = [[round(x, 2), round(y, 2)] for x, y in stille(str(aus), a.noise, a.pause + 0.15)]
    rest = [r for r in rest if r[0] > 0.05 and r[1] < dauer(str(aus)) - 0.05]
    neu = dauer(str(aus))
    bericht = {"original": orig, "original_dauer": round(total, 2), "schnitt_dauer": round(neu, 2),
               "schnitte": len(stuecke) - 1, "pause_ziel": a.pause, "stuecke": stuecke,
               "restpausen": rest}
    schreibe_json(str(aus.with_suffix(".json")), bericht)
    print(f"Original {total:.1f}s → Schnitt {neu:.1f}s ({len(stuecke) - 1} Schnitte, "
          f"{100 * (1 - neu / total):.0f}% kürzer)")
    if rest:
        print(f"ACHTUNG: {len(rest)} Pause(n) länger als {a.pause + 0.15:.2f}s im Schnitt: {rest}")
    else:
        print("Prüfung: keine Pausen über "
              f"{a.pause + 0.15:.2f}s im fertigen Schnitt.")
    print(f"→ {aus}")


if __name__ == "__main__":
    main()
