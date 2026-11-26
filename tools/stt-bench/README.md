# Speech-to-text test bench (Mac, Apple silicon)

These scripts compare speech models on real voice notes, locally. They were used on 26 Nov 2026 to choose Whisper large-v3 with a product-name hint (see `prog.md` at the repo root). They are not part of the app.

Voice notes are client data. Keep the recordings and the results in the git-ignored `samples/` folder, and never commit them.

## Setup (once)

```
cd tools/stt-bench
uv sync                                   # Whisper (MLX) and Cohere (transformers)

# Jais-ASR needs its own env: mlx-vlm at a fixed commit plus IFM's patch
git clone https://github.com/Blaizzy/mlx-vlm.git jais-mlx-vlm && cd jais-mlx-vlm
git checkout 6ecadd767ca1c7c54763289c750dd180d7945037
uv venv --python 3.12 .venv && VIRTUAL_ENV=.venv uv pip install -e . torch
uv run --with huggingface_hub hf download IFM/Jais-ASR-MLX-4bit mlx-vlm-jais-asr.patch --local-dir .
git apply mlx-vlm-jais-asr.patch && cd ..
```

Models download on first use: Whisper large-v3 MLX is about 3.1 GB, and Jais-ASR-MLX-4bit is about 4.5 GB. Cohere Transcribe Arabic needs a Hugging Face login that has accepted its terms.

## Run

```
./prep.sh ../../samples/kahraman/voice ../../samples/kahraman/wav           # any audio -> 16 kHz mono WAV
uv run python run_whisper.py      ../../samples/kahraman/wav ../../samples/kahraman/whisper.jsonl
uv run python run_whisper_hint.py ../../samples/kahraman/wav ../../samples/kahraman/whisper_hint.jsonl
MAX_TOKENS=400 jais-mlx-vlm/.venv/bin/python run_jais.py ../../samples/kahraman/wav ../../samples/kahraman/jais.jsonl on
```

Each script writes one JSON line per note: the file, the text and the seconds taken.

Notes:
- WhatsApp sometimes saves voice notes with the wrong file ending (a `.jpeg` that is really audio). `ffmpeg` reads them anyway. `prep.sh` only picks up audio endings, so convert those by hand.
- Jais hears about 30 seconds at a time. Cut longer notes first, for example `ffmpeg -i note.wav -f segment -segment_time 25 -c copy part%02d.wav`.
- Never force the language for Whisper. Forcing Arabic made it worse in an outside test.
- `run_whisper_hint.py` has the hint word list hard-coded. In the app it should be built from the product table.

Score each note on what matters to the assistant: the product name, the quantity and the question. Word error rate needs exact reference transcripts, which we do not have.
