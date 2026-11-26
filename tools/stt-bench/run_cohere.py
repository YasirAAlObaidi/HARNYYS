"""Cohere Transcribe Arabic on the Mac GPU (MPS). It needs the language up front: we pass 'ar' (it has no detection)."""
import json, sys, time
from pathlib import Path
import torch
from transformers import AutoProcessor, CohereAsrForConditionalGeneration
from transformers.audio_utils import load_audio

src, out = Path(sys.argv[1]), Path(sys.argv[2])
lang = sys.argv[3] if len(sys.argv) > 3 else "ar"
repo = "CohereLabs/cohere-transcribe-arabic-07-2026"
device = "mps" if torch.backends.mps.is_available() else "cpu"
processor = AutoProcessor.from_pretrained(repo)
model = CohereAsrForConditionalGeneration.from_pretrained(repo, dtype=torch.float16).to(device).eval()
with out.open("w", encoding="utf-8") as fh:
    for wav in sorted(src.glob("*.wav")):
        start = time.perf_counter()
        audio = load_audio(str(wav), sampling_rate=16000)
        inputs = processor(audio=audio, sampling_rate=16000, return_tensors="pt", language=lang)
        chunks = inputs.pop("audio_chunk_index", None)
        inputs.to(model.device, dtype=model.dtype)
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=256)
        kw = {"audio_chunk_index": chunks, "language": lang} if chunks is not None else {}
        text = processor.decode(ids, skip_special_tokens=True, **kw)
        text = text[0] if isinstance(text, list) else text
        row = {"file": wav.name, "model": f"cohere-transcribe-arabic ({lang})", "language": lang,
               "text": text.strip(), "seconds": round(time.perf_counter() - start, 2)}
        fh.write(json.dumps(row, ensure_ascii=False) + "\n"); print(row, flush=True)
