#!/usr/bin/env python3
"""Take-Finder: wählt pro Satz den besten Take.

Mit Skript:  takes.py <transcript.json> <takes.json> --skript skript.txt
Ohne Skript: takes.py <transcript.json> <takes.json>          (freie Rede)

Ergebnis takes.json:
  saetze:    pro Skript-Satz alle gefundenen Takes mit Score und der gewählte Take
  segmente:  die zu behaltenden Stücke im Original [start, ende] (Wortzeiten, noch ohne Pausen-Feinschliff)
  verworfen: Passagen, die keinem Satz zugeordnet wurden (Versprecher, alte Takes, freie Einschübe)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gemeinsam import (aehnlich, ist_fuellwort, lade_woerter, lcs_paare, norm,  # noqa: E402
                       saetze_aus_skript, schreibe_json)

PAUSE_PHRASE = 0.45  # ab dieser Lücke beginnt bei freier Rede eine neue Phrase


def kandidaten(satz_w, T, idx):
    """Alle Takes eines Satzes in den (füllwortfreien) Transkriptwörtern."""
    L = len(satz_w)
    worte = [T[k]["text"] for k in idx]
    gesehen, raus = set(), []
    for i in range(len(worte)):
        if not (aehnlich(worte[i], satz_w[0]) or (L > 1 and aehnlich(worte[i], satz_w[1]))):
            continue
        fenster = worte[i:i + L + 4]
        paare = lcs_paare(satz_w, fenster)
        if not paare:
            continue
        a, b = i + paare[0][1], i + paare[-1][1]
        if (a, b) in gesehen:
            continue
        gesehen.add((a, b))
        treffer, spanne = len(paare), b - a + 1
        abdeckung = treffer / L
        if abdeckung < 0.6:
            continue
        score = 2 * treffer / (L + spanne)
        if not aehnlich(worte[b], satz_w[-1]):
            score -= 0.15  # Satz nicht zu Ende gesprochen
        raus.append({"von": a, "bis": b, "score": round(score, 3), "abdeckung": round(abdeckung, 3)})
    return raus


def waehle(kand_listen):
    """DP: pro Satz ein Take, zeitlich aufsteigend, Summe der Scores maximal.
    Bei Gleichstand gewinnt der spätere Take (meist der sauberste Versuch)."""
    best = {-1: (0.0, [])}  # letztes 'bis' -> (wert, auswahl)
    for liste in kand_listen:
        neu = {}
        for ende, (wert, wahl) in best.items():
            # Satz fehlt (Strafe)
            kand = [(ende, wert - 1.0, wahl + [None])]
            for k, c in enumerate(liste):
                if c["von"] > ende:
                    kand.append((c["bis"], wert + c["score"] + 0.0001 * c["von"], wahl + [k]))
            for e, w, a in kand:
                if e not in neu or w > neu[e][0]:
                    neu[e] = (w, a)
        best = neu
    return max(best.values(), key=lambda x: x[0])[1]


def segmente_aus_bereich(T, idx, a, b, satz=""):
    """Wörter idx[a..b] -> zusammenhängende Segmente (Füllwörter fallen raus)."""
    laeufe, lauf = [], [idx[a]]
    for k in idx[a + 1:b + 1]:
        if k == lauf[-1] + 1:
            lauf.append(k)
        else:  # dazwischen lag ein Füllwort -> hier schneiden
            laeufe.append(lauf)
            lauf = [k]
    laeufe.append(lauf)
    return [{"start": round(T[l[0]]["start"], 3), "ende": round(T[l[-1]]["end"], 3),
             "text": " ".join(T[k]["text"] for k in l), "satz": satz} for l in laeufe]


def mit_skript(T, idx, skript):
    saetze = saetze_aus_skript(skript)
    satz_worte = [[w for w in s.split() if norm(w)] for s in saetze]
    kand_listen = [kandidaten(sw, T, idx) for sw in satz_worte]
    wahl = waehle(kand_listen)
    ergebnis, segmente, benutzt = [], [], set()
    for s, sw, liste, k in zip(saetze, satz_worte, kand_listen, wahl):
        takes = []
        for n, c in enumerate(liste):
            w0, w1 = T[idx[c["von"]]], T[idx[c["bis"]]]
            takes.append({"nr": n + 1, "start": w0["start"], "ende": w1["end"], "score": c["score"],
                          "text": " ".join(T[idx[j]]["text"] for j in range(c["von"], c["bis"] + 1))})
        eintrag = {"satz": s, "takes": takes, "gewaehlt": None if k is None else k + 1}
        if k is not None:
            c = liste[k]
            segmente += segmente_aus_bereich(T, idx, c["von"], c["bis"], s)
            benutzt.update(range(c["von"], c["bis"] + 1))
        ergebnis.append(eintrag)
    return ergebnis, segmente, benutzt


def phrasen(T, idx):
    """Freie Rede: an Satzzeichen oder Pausen in Phrasen teilen."""
    teile, aktuell = [], []
    for j, k in enumerate(idx):
        if aktuell:
            vorher = T[idx[aktuell[-1]]]
            if T[k]["start"] - vorher["end"] >= PAUSE_PHRASE or vorher["text"][-1:] in ".!?…":
                teile.append(aktuell)
                aktuell = []
        aktuell.append(j)
    if aktuell:
        teile.append(aktuell)
    return teile


def ist_neuanlauf(p, q, T, idx):
    """Phrase p ist ein abgebrochener Anlauf, wenn q mit denselben Wörtern neu beginnt."""
    a = [T[idx[j]]["text"] for j in p]
    b = [T[idx[j]]["text"] for j in q]
    n = 0
    while n < min(len(a), len(b)) and aehnlich(a[n], b[n]):
        n += 1
    return n >= 2 or (n >= 1 and len(a) <= 2) or (n >= 0.6 * len(a) and n >= 1)


def frei(T, idx):
    teile = phrasen(T, idx)
    segmente, benutzt, ergebnis = [], set(), []
    for n, p in enumerate(teile):
        folgende = teile[n + 1:n + 3]
        if any(ist_neuanlauf(p, q, T, idx) for q in folgende):
            continue
        # direkt doppelte Wörter ("ich ich") -> das erste fällt weg
        behalten = [j for i, j in enumerate(p)
                    if not (i + 1 < len(p) and norm(T[idx[j]]["text"]) == norm(T[idx[p[i + 1]]]["text"]))]
        text = " ".join(T[idx[j]]["text"] for j in behalten)
        # zusammenhängende Läufe bilden
        lauf = [behalten[0]]
        for j in behalten[1:] + [None]:
            if j is not None and j == lauf[-1] + 1:
                lauf.append(j)
                continue
            segmente += segmente_aus_bereich(T, idx, lauf[0], lauf[-1], text)
            if j is not None:
                lauf = [j]
        benutzt.update(behalten)
        ergebnis.append({"satz": text, "takes": [], "gewaehlt": None})
    return ergebnis, segmente, benutzt


def verworfene(T, idx, benutzt):
    raus, lauf = [], []
    for j in range(len(idx)):
        if j in benutzt:
            if lauf:
                raus.append(lauf)
            lauf = []
        else:
            lauf.append(j)
    if lauf:
        raus.append(lauf)
    return [{"start": T[idx[l[0]]]["start"], "ende": T[idx[l[-1]]]["end"],
             "text": " ".join(T[idx[j]]["text"] for j in l)} for l in raus]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transkript")
    ap.add_argument("ziel")
    ap.add_argument("--skript")
    a = ap.parse_args()
    T = lade_woerter(a.transkript)
    idx = [k for k, w in enumerate(T) if not ist_fuellwort(w["text"])]
    fuell = [T[k] for k in range(len(T)) if ist_fuellwort(T[k]["text"])]
    if a.skript:
        saetze, segmente, benutzt = mit_skript(T, idx, Path(a.skript).read_text(encoding="utf-8"))
        modus = "skript"
    else:
        saetze, segmente, benutzt = frei(T, idx)
        modus = "frei"
    segmente.sort(key=lambda s: s["start"])
    daten = {"modus": modus, "saetze": saetze, "segmente": segmente,
             "verworfen": verworfene(T, idx, benutzt), "fuellwoerter": fuell}
    schreibe_json(a.ziel, daten)

    print(f"Modus: {modus}")
    for s in saetze:
        if modus == "skript":
            g = s["gewaehlt"]
            info = "FEHLT im Transkript!" if g is None else f"Take {g} von {len(s['takes'])}"
            print(f"  [{info}] {s['satz']}")
            for t in s["takes"]:
                mark = "→" if t["nr"] == g else " "
                print(f"     {mark} {t['nr']}: {t['start']:.2f}-{t['ende']:.2f}s  score {t['score']:.2f}  „{t['text']}“")
        else:
            print(f"  ✓ {s['satz']}")
    for v in daten["verworfen"]:
        print(f"  ✗ verworfen {v['start']:.2f}-{v['ende']:.2f}s: „{v['text']}“")
    print(f"Segmente: {len(segmente)}  →  {a.ziel}")


if __name__ == "__main__":
    main()
