"""Whisper large-v3 with a vocabulary hint: product and origin names it should expect."""
import json, sys, time
from pathlib import Path
import mlx_whisper

HINT = ("قهوة نيكاراغوا، غواتيمالا، كولومبيا توليما واشد، البرازيل، إثيوبيا، جونية ٢٠ كيلو. "
        "Nicaragua, Guatemala, Colombia Tolima, Brazil, Fiorenzato, VBM, Gene Cafe.")
src, out = Path(sys.argv[1]), Path(sys.argv[2])
with out.open("w", encoding="utf-8") as fh:
    for wav in sorted(src.glob("*.wav")):
        start = time.perf_counter()
        r = mlx_whisper.transcribe(str(wav), path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
                                   temperature=0.0, condition_on_previous_text=False, initial_prompt=HINT)
        row = {"file": wav.name, "text": r["text"].strip(), "seconds": round(time.perf_counter() - start, 2)}
        fh.write(json.dumps(row, ensure_ascii=False) + "\n"); print(row, flush=True)
