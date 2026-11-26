"""Jais-ASR 4-bit (MLX, patched mlx-vlm) over every WAV in a folder. Language detected; code-switching on."""
import json, sys, time
from pathlib import Path
from mlx_vlm import generate, load

src, out = Path(sys.argv[1]), Path(sys.argv[2])
code_switch = (sys.argv[3] if len(sys.argv) > 3 else "on") == "on"
repo = "IFM/Jais-ASR-MLX-4bit"
model, processor = load(repo, trust_remote_code=True)
tok = getattr(processor, "tokenizer", processor)
prompt = tok.apply_chat_template([{"role": "user", "content": [{"type": "audio"}]}], tokenize=False,
                                 add_generation_prompt=True, code_switch=code_switch)
with out.open("w", encoding="utf-8") as fh:
    for wav in sorted(src.glob("*.wav")):
        start = time.perf_counter()
        r = generate(model, processor, prompt, audio=[str(wav)], max_tokens=int(__import__("os").environ.get("MAX_TOKENS", "256")), temperature=0.0,
                     repetition_penalty=1.05, verbose=False)
        text = getattr(r, "text", r)
        row = {"file": wav.name, "model": f"jais-asr-4bit (code_switch={'on' if code_switch else 'off'})",
               "text": str(text).strip(), "seconds": round(time.perf_counter() - start, 2)}
        fh.write(json.dumps(row, ensure_ascii=False) + "\n"); print(row, flush=True)
