#!/bin/sh
# Convert every audio file in a folder to 16 kHz mono WAV for the models. Usage: prep.sh SRC_DIR OUT_DIR
set -eu
src="$1"; out="$2"; mkdir -p "$out"
find "$src" -type f \( -iname '*.opus' -o -iname '*.ogg' -o -iname '*.m4a' -o -iname '*.mp3' -o -iname '*.wav' -o -iname '*.aac' -o -iname '*.aiff' -o -iname '*.amr' -o -iname '*.mp4' \) | while read -r f; do
  name="$(basename "$f")"; base="${name%.*}"
  ffmpeg -nostdin -loglevel error -y -i "$f" -ac 1 -ar 16000 "$out/$base.wav"
  echo "$out/$base.wav"
done
