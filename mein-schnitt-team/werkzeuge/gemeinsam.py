"""Gemeinsame Helfer für das Schnitt-Team: Transkript laden, Text normalisieren,
Stille messen, unscharfer Wortabgleich. Nur Python-Standardbibliothek."""
import json
import re
import subprocess
import unicodedata
from difflib import SequenceMatcher

FUELLWOERTER = {"äh", "ähm", "öhm", "ehm", "hm", "hmm", "mhm", "äähm", "ääh", "eh", "em", "öh"}


def lade_woerter(pfad):
    """Liest transcript.json von `hyperframes transcribe` -> Liste {text,start,end}."""
    with open(pfad, encoding="utf-8") as f:
        d = json.load(f)
    woerter = d if isinstance(d, list) else d.get("words", [])
    raus = []
    for w in woerter:
        t = str(w.get("text", "")).strip()
        if not t or set(t) <= set("♪�.,!?-…"):
            continue
        raus.append({"text": t, "start": float(w["start"]), "end": float(w["end"])})
    return raus


def norm(wort):
    w = unicodedata.normalize("NFC", wort.lower())
    w = re.sub(r"[^\wäöüß]", "", w)
    return w


def aehnlich(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) <= 3:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def ist_fuellwort(wort):
    return norm(wort) in FUELLWOERTER


def saetze_aus_skript(text):
    text = re.sub(r"\s+", " ", text.strip())
    teile = re.split(r"(?<=[.!?…])\s+", text)
    return [t.strip() for t in teile if t.strip()]


def lcs_paare(a, b, gleich=aehnlich):
    """Unscharfe LCS zwischen zwei Wortlisten -> Liste (i, j) passender Indizes."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if gleich(a[i], b[j]):
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    i = j = 0
    paare = []
    while i < n and j < m:
        if gleich(a[i], b[j]) and dp[i][j] == dp[i + 1][j + 1] + 1:
            paare.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return paare


def dauer(pfad):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", pfad],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def stille(pfad, noise="-35dB", mindauer=0.25):
    """ffmpeg silencedetect -> Liste [start, ende] in Sekunden."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", pfad, "-vn", "-af",
         f"silencedetect=noise={noise}:d={mindauer}", "-f", "null", "-"],
        capture_output=True, text=True)
    total = dauer(pfad)
    luecken, start = [], None
    for zeile in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", zeile)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", zeile)
        if m and start is not None:
            luecken.append([start, float(m.group(1))])
            start = None
    if start is not None:
        luecken.append([start, total])
    return luecken


def schreibe_json(pfad, daten):
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
