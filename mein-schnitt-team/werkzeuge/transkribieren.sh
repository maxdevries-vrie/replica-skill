#!/usr/bin/env bash
# Lokale Transkription mit Wort-Zeitstempeln (Deutsch, mehrsprachiges Whisper-Modell).
# Aufruf: werkzeuge/transkribieren.sh <video> <ziel.json> [modell]
# Nie ein .en-Modell verwenden: das übersetzt Deutsch ins Englische.
set -euo pipefail
EIN="$(realpath "$1")"; ZIEL="$2"; MODELL="${3:-small}"
case "$MODELL" in *.en) echo "Fehler: .en-Modelle sind für Deutsch verboten." >&2; exit 1;; esac
HIER="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
export NODE_USE_ENV_PROXY=1   # Node-Downloads (Modell) laufen sonst am Proxy vorbei
("$HIER/werkzeuge/hf" transcribe "$EIN" --model "$MODELL" --language de \
  --engine whisper --dir "$TMP" --json) > "$TMP/ergebnis.json"
grep -q '"ok":true' "$TMP/ergebnis.json" || { cat "$TMP/ergebnis.json" >&2; exit 1; }
mkdir -p "$(dirname "$ZIEL")"
mv "$TMP/transcript.json" "$ZIEL"
rm -rf "$TMP"
echo "Transkript: $ZIEL"
