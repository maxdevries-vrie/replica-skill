#!/usr/bin/env python3
"""Untertitel- und Grafik-Agent: baut ein HyperFrames-Projekt auf den fertigen Schnitt.

untertitel.py <schnitt.mp4> <schnitt-transcript.json> <projektordner>
              [--skript skript.txt] [--titel "Hook-Text"] [--broll-plan plan.json]

- Wörter kommen aus der NEUEN Transkription des Schnitts; die Schreibweise wird mit dem
  Skript abgeglichen (Skript gewinnt bei Rechtschreibung und Satzzeichen).
- Untertitel als kurze Zeilen (2–4 Wörter), die Zeile erscheint als Ganzes – nicht Wort für Wort.
- *Sternchen* im Skript markieren Betonungswörter -> farbig hervorgehoben.
- --titel blendet oben einen Hook-Text für die ersten Sekunden ein.
- --broll-plan: JSON-Liste [{"datei": "pfad", "start": 3.2, "dauer": 2.0, "media_start": 0}]
  Zeiten beziehen sich auf den Schnitt. Bilder bekommen einen leichten Zoom, Videos laufen stumm.
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gemeinsam import dauer, ist_fuellwort, lade_woerter, lcs_paare, norm, stille  # noqa: E402

MAX_WOERTER = 4
MAX_ZEICHEN = 20
PAUSE_BRUCH = 0.15
FARBE_BETONUNG = "#FFD60A"


EINHEITEN = {"€", "%", "$", "Euro", "Prozent", "Cent"}


def skript_woerter(text):
    """Skript in Wörter; eine Einheit (€, %) hängt am Zahlwort davor ("300 €" = ein Wort)."""
    raus = []
    for roh in text.split():
        betont = "*" in roh
        wort = roh.replace("*", "")
        if wort.strip(".,!?:;") in EINHEITEN and raus:
            raus[-1]["text"] += "\u00a0" + wort  # geschütztes Leerzeichen: nie umbrechen
            raus[-1]["betont"] = raus[-1]["betont"] or betont
            continue
        if norm(wort) or wort in EINHEITEN:
            raus.append({"text": wort, "betont": betont})
    return raus


def _verteilen(sw, t0, t1):
    """Skriptwörter ohne sichere Zeit gleichmäßig (nach Länge) auf [t0, t1] verteilen."""
    t1 = max(t1, t0 + 0.12 * len(sw))
    laengen = [max(2, len(w["text"])) for w in sw]
    gesamt, t, raus = sum(laengen), t0, []
    for w, l in zip(sw, laengen):
        d = (t1 - t0) * l / gesamt
        raus.append({"text": w["text"], "betont": w["betont"], "start": t, "end": t + d, "geschaetzt": True})
        t += d
    return raus


def korrigieren(woerter, skript):
    """Mit Skript gilt der Skripttext vollständig: sicher erkannte Wörter (unscharfe LCS) behalten
    ihre Zeit, alles dazwischen wird durch die Skriptwörter ersetzt und zeitlich verteilt."""
    if not skript:
        for w in woerter:
            w["betont"] = False
        return woerter
    # "Euro"/"€" als eigenes Transkriptwort an die Zahl davor hängen
    T = []
    for w in woerter:
        if w["text"].strip(".,!?") in EINHEITEN and T:
            T[-1]["end"] = w["end"]
            continue
        T.append(dict(w))
    S = skript_woerter(skript)
    paare = lcs_paare([w["text"] for w in T], [s["text"] for s in S])
    raus = []
    vor_i, vor_j = -1, -1
    for i, j in paare + [(len(T), len(S))]:
        luecke_s = S[vor_j + 1:j]
        if luecke_s:
            t0 = T[vor_i]["end"] if vor_i >= 0 else (T[0]["start"] if T else 0.0)
            t1 = T[i]["start"] if i < len(T) else (T[-1]["end"] if T else t0 + 0.5)
            if vor_i + 1 < i:  # es gab Transkriptwörter in der Lücke -> deren Spanne nehmen
                t0, t1 = T[vor_i + 1]["start"], T[i - 1]["end"]
            raus += _verteilen(luecke_s, t0, t1)
        if i < len(T):
            raus.append({"text": S[j]["text"], "betont": S[j]["betont"], "start": T[i]["start"], "end": T[i]["end"]})
        vor_i, vor_j = i, j
    raus.sort(key=lambda w: w["start"])
    return raus


def zeiten_glaetten(woerter, luecken, total):
    """Wortenden, die in eine Stille ragen, auf den Beginn der Stille ziehen."""
    for n, w in enumerate(woerter):
        for a, b in luecken:
            if a < w["end"] <= b and a > w["start"]:
                w["end"] = a
        if n + 1 < len(woerter):
            w["end"] = min(w["end"], woerter[n + 1]["start"])
        w["end"] = min(w["end"], total)
    return woerter


def gruppieren(woerter):
    gruppen, akt = [], []
    for n, w in enumerate(woerter):
        akt.append(w)
        text = " ".join(x["text"] for x in akt)
        naechstes = woerter[n + 1] if n + 1 < len(woerter) else None
        satzende_passt = (naechstes is not None and naechstes["text"][-1:] in ".!?…"
                          and len(akt) < MAX_WOERTER + 1 and len(text) + 1 + len(naechstes["text"]) <= MAX_ZEICHEN + 7)
        bruch = (naechstes is None or w["text"][-1:] in ".!?…:"
                 or naechstes["start"] - w["end"] >= PAUSE_BRUCH
                 or (w["text"][-1:] == "," and len(akt) >= 2)
                 or (not satzende_passt and (len(akt) >= MAX_WOERTER
                                             or len(text) + 1 + len(naechstes["text"]) > MAX_ZEICHEN)))
        if bruch:
            gruppen.append(akt)
            akt = []
    # Einzelnes Mini-Wort ("und", "es") an die nächste Zeile hängen
    fertig, n = [], 0
    while n < len(gruppen):
        g = gruppen[n]
        if (len(g) == 1 and len(g[0]["text"]) <= 4 and g[0]["text"][-1:] not in ".!?" and n + 1 < len(gruppen)
                and len(gruppen[n + 1]) < MAX_WOERTER):
            gruppen[n + 1] = g + gruppen[n + 1]
        else:
            fertig.append(g)
        n += 1
    return fertig


def zeitplan(gruppen, total):
    plan = []
    for n, g in enumerate(gruppen):
        start = max(0.12, g[0]["start"] - 0.05)
        ende = g[-1]["end"] + 0.12
        if n + 1 < len(gruppen):
            ende = min(ende, max(start + 0.3, gruppen[n + 1][0]["start"] - 0.05))
        ende = min(max(ende, start + 0.35), total - 0.02)
        if plan:
            start = max(start, plan[-1]["ende"])
        plan.append({"start": round(start, 3), "ende": round(ende, 3), "woerter": g})
    return plan


def wort_html(w):
    t = html.escape(w["text"])
    return f'<span class="b">{t}</span>' if w["betont"] else t


def untertitel_html(plan, unten=640):
    gruppen_html, js = [], []
    for n, g in enumerate(plan):
        text = " ".join(wort_html(w) for w in g["woerter"])
        gruppen_html.append(f'    <div id="ut-{n}" class="ut"><span class="ut-t">{text}</span></div>')
        js.append(f"[{g['start']},{g['ende']}]")
    return f"""<template>
  <style>
    #root {{ position: absolute; inset: 0; }}
    .ut {{ position: absolute; left: 0; right: 0; bottom: {unten}px; padding: 0 90px;
          text-align: center; overflow: visible; opacity: 0; visibility: hidden; }}
    .ut-t {{ display: inline-block; font-family: Montserrat; font-weight: 900;
            font-size: 84px; line-height: 1.08; color: #fff; letter-spacing: -0.5px;
            -webkit-text-stroke: 12px #000; paint-order: stroke fill;
            text-shadow: 0 6px 18px rgba(0,0,0,.45); }}
    .ut-t .b {{ color: {FARBE_BETONUNG}; }}
  </style>
  <div id="root" data-composition-id="untertitel" data-width="1080" data-height="1920">
{chr(10).join(gruppen_html)}
  </div>
  <script>
    const zeiten = [{",".join(js)}];
    const tl = gsap.timeline({{ paused: true }});
    const fit = window.__hyperframes && window.__hyperframes.fitTextFontSize;
    zeiten.forEach(([s, e], i) => {{
      const g = document.getElementById("ut-" + i);
      const t = g.querySelector(".ut-t");
      if (fit) {{
        const r = fit(t.textContent, {{ fontFamily: "Montserrat", fontWeight: 900, maxWidth: 900,
                                        baseFontSize: 84, minFontSize: 48, step: 2 }});
        if (r && r.fontSize) t.style.fontSize = r.fontSize + "px";
      }}
      tl.set(g, {{ visibility: "visible" }}, s);
      tl.fromTo(g, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.06, ease: "none" }}, s);
      tl.fromTo(t, {{ scale: 0.86, y: 14 }}, {{ scale: 1, y: 0, duration: 0.16, ease: "back.out(2.2)" }}, s);
      tl.to(g, {{ opacity: 0, duration: 0.06, ease: "power2.in" }}, e - 0.06);
      tl.set(g, {{ opacity: 0, visibility: "hidden" }}, e);
    }});
    window.__timelines["untertitel"] = tl;
  </script>
</template>
"""


def titel_html(text, dauer_s):
    t = html.escape(text)
    return f"""<template>
  <style>
    #root {{ position: absolute; inset: 0; }}
    #titel-box {{ position: absolute; left: 0; right: 0; top: 250px; text-align: center; padding: 0 80px; }}
    #titel-text {{ display: inline-block; font-family: Montserrat; font-weight: 900; font-size: 74px;
                  line-height: 1.1; color: #2A2018; background: {FARBE_BETONUNG}; padding: 18px 34px;
                  border-radius: 22px; box-shadow: 0 10px 30px rgba(0,0,0,.35); }}
  </style>
  <div id="root" data-composition-id="titel" data-width="1080" data-height="1920">
    <div id="titel-box"><span id="titel-text" data-var-text="titel">{t}</span></div>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.fromTo("#titel-text", {{ y: -60, scale: 0.8, opacity: 0 }},
              {{ y: 0, scale: 1, opacity: 1, duration: 0.35, ease: "back.out(1.8)" }}, 0.05);
    tl.to("#titel-text", {{ y: -40, opacity: 0, duration: 0.25, ease: "power2.in" }}, {dauer_s - 0.3:.2f});
    window.__timelines["titel"] = tl;
  </script>
</template>
"""


def broll_html(eintraege, proj, total):
    """B-Roll als eigene Sub-Composition: Bilder mit leichtem Zoom, Videos stumm."""
    teile, js = [], []
    for n, b in enumerate(eintraege):
        q = Path(b["datei"])
        ziel = proj / "assets" / "broll" / f"{n:02d}-{q.name}"
        verlinken(q.resolve(), ziel)
        rel = f"assets/broll/{ziel.name}"
        s = round(float(b["start"]), 3)
        d = round(min(float(b["dauer"]), total - s), 3)
        bid = f"br-{n}"
        stil = "position:absolute;left:0;top:0;width:1080px;height:1920px;object-fit:cover"
        if q.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}:
            teile.append(f'    <video id="{bid}" class="clip" src="{rel}" muted playsinline data-start="{s}" '
                         f'data-duration="{d}" data-media-start="{b.get("media_start", 0)}" style="{stil}"></video>')
        else:
            teile.append(f'    <div id="{bid}" class="clip" data-start="{s}" data-duration="{d}" '
                         f'style="position:absolute;inset:0;overflow:hidden">'
                         f'<img id="{bid}-img" src="{rel}" style="{stil}"></div>')
            js.append(f'tl.fromTo("#{bid}-img", {{scale:1.0}}, {{scale:1.08, duration:{d}, ease:"none"}}, {s});')
        js.append(f'tl.fromTo("#{bid}", {{opacity:0}}, {{opacity:1, duration:0.12}}, {s});')
        js.append(f'tl.to("#{bid}", {{opacity:0, duration:0.12}}, {round(s + d - 0.13, 3)});')
    nl = chr(10)
    return f"""<template>
  <style>#root {{ position: absolute; inset: 0; }}</style>
  <div id="root" data-composition-id="broll" data-width="1080" data-height="1920">
{nl.join(teile)}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {(nl + "    ").join(js)}
    window.__timelines["broll"] = tl;
  </script>
</template>
"""


def verlinken(quelle, ziel):
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists():
        ziel.unlink()
    try:
        os.link(quelle, ziel)
    except OSError:
        shutil.copy2(quelle, ziel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("schnitt")
    ap.add_argument("transkript")
    ap.add_argument("projekt")
    ap.add_argument("--skript")
    ap.add_argument("--titel")
    ap.add_argument("--titel-dauer", type=float, default=2.6)
    ap.add_argument("--broll-plan")
    ap.add_argument("--farbe", default=None, help="Farbe für Betonung und Hook-Box, z. B. #E9D8BE")
    ap.add_argument("--unten", type=int, default=640, help="Abstand Untertitel zum unteren Rand in px")
    a = ap.parse_args()
    global FARBE_BETONUNG
    if a.farbe:
        FARBE_BETONUNG = a.farbe

    proj = Path(a.projekt)
    (proj / "compositions").mkdir(parents=True, exist_ok=True)
    total = round(dauer(a.schnitt), 3)
    verlinken(Path(a.schnitt).resolve(), proj / "assets" / "schnitt.mp4")
    shutil.copy2(Path(__file__).parent.parent / "vorlagen" / "gsap.min.js", proj / "assets" / "gsap.min.js")

    skript = Path(a.skript).read_text(encoding="utf-8") if a.skript else ""
    woerter = [w for w in lade_woerter(a.transkript) if not ist_fuellwort(w["text"])]
    woerter = [w for w in woerter if w["start"] < total - 0.05]  # Whisper-Geister am Ende
    woerter = korrigieren(woerter, skript)
    woerter = zeiten_glaetten(woerter, stille(a.schnitt, "-35dB", 0.1), total)
    plan = zeitplan(gruppieren(woerter), total)
    (proj / "compositions" / "untertitel.html").write_text(untertitel_html(plan, a.unten), encoding="utf-8")

    hosts = []
    if a.broll_plan:
        eintraege = json.loads(Path(a.broll_plan).read_text(encoding="utf-8"))
        (proj / "compositions" / "broll.html").write_text(broll_html(eintraege, proj, total), encoding="utf-8")
        hosts.append(
            f'    <div id="broll" data-composition-id="broll" data-composition-src="compositions/broll.html" '
            f'data-start="0" data-duration="{total}" data-track-index="10" data-track-kind="graphics" '
            f'data-width="1080" data-height="1920" style="z-index:10"></div>')
    if a.titel:
        (proj / "compositions" / "titel.html").write_text(titel_html(a.titel, a.titel_dauer), encoding="utf-8")
        hosts.append(
            f'    <div id="titel" data-composition-id="titel" data-composition-src="compositions/titel.html" '
            f'data-start="0" data-duration="{a.titel_dauer}" data-track-index="20" data-track-kind="graphics" '
            f'data-width="1080" data-height="1920" style="z-index:20"></div>')
    hosts.append(
        f'    <div id="untertitel" data-composition-id="untertitel" data-composition-src="compositions/untertitel.html" '
        f'data-start="0" data-duration="{total}" data-track-index="30" data-track-kind="captions" '
        f'data-width="1080" data-height="1920" style="z-index:30"></div>')

    variablen = json.dumps([{"id": "titel", "type": "string", "label": "Hook-Titel",
                             "default": a.titel or ""}], ensure_ascii=False)
    index = f"""<!doctype html>
<html data-composition-variables='{html.escape(variablen, quote=True)}'>
<head><meta charset="utf-8"><script src="assets/gsap.min.js"></script><style>html,body{{margin:0;background:#000}}</style></head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
    <video id="aufnahme" class="clip" src="assets/schnitt.mp4" playsinline data-has-audio="true" data-volume="1"
      data-start="0" data-duration="{total}" data-track-index="1"
      style="position:absolute;left:0;top:0;width:1080px;height:1920px;object-fit:cover;z-index:1"></video>
{chr(10).join(hosts)}
  </div>
  <script>
    window.__timelines["main"] = gsap.timeline({{ paused: true }});
  </script>
</body>
</html>
"""
    (proj / "index.html").write_text(index, encoding="utf-8")
    (proj / "untertitel.json").write_text(json.dumps(
        [{"start": g["start"], "ende": g["ende"], "text": " ".join(w["text"] for w in g["woerter"])} for g in plan],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(plan)} Untertitel-Zeilen, Dauer {total}s → {proj}/index.html")
    for g in plan:
        print(f"  {g['start']:6.2f}-{g['ende']:6.2f}  {' '.join(w['text'] for w in g['woerter'])}")


if __name__ == "__main__":
    main()
