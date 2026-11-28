"""Whisper large-v3 (MLX) over every WAV in a folder. Language is detected, never forced."""
import json, sys, time
from pathlib import Path
import mlx_whisper

src, out = Path(sys.argv[1]), Path(sys.argv[2])
with out.open("w", encoding="utf-8") as fh:
    for wav in sorted(src.glob("*.wav")):
        start = time.perf_counter()
        r = mlx_whisper.transcribe(str(wav), path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
                                   temperature=0.0, condition_on_previous_text=False)
        row = {"file": wav.name, "model": "whisper-large-v3", "language": r.get("language"),
               "text": r["text"].strip(), "seconds": round(time.perf_counter() - start, 2)}
        fh.write(json.dumps(row, ensure_ascii=False) + "\n"); print(row, flush=True)
