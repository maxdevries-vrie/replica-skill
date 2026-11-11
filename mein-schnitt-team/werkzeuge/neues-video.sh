#!/usr/bin/env bash
# Legt ein neues Video-Projekt an und schützt die Originale.
# Aufruf: werkzeuge/neues-video.sh <name> <rohaufnahme> [skript.txt] [broll-ordner]
set -euo pipefail
NAME="$1"; ROH="$2"; SKRIPT="${3:-}"; BROLL="${4:-}"
HIER="$(cd "$(dirname "$0")/.." && pwd)"
V="$HIER/videos/$NAME"
mkdir -p "$V"/{roh,arbeit,hf,vorschau,export}
cp -n "$ROH" "$V/roh/"
chmod a-w "$V/roh/"*            # Originale schreibgeschützt
[ -n "$SKRIPT" ] && cp "$SKRIPT" "$V/skript.txt"
[ -n "$BROLL" ] && ln -sfn "$(realpath "$BROLL")" "$V/broll"
echo "Projekt: $V"
ffprobe -v error -show_entries stream=codec_type,width,height,r_frame_rate:format=duration -of compact "$V/roh/$(basename "$ROH")"
