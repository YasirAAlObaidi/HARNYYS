"""One-off: download the catalogue's product images so the app can upload them to WhatsApp itself.

Run:  cd apps/server && uv run python -I ../../deploy/clients/kahraman/fetch_images.py
Needs Pillow (dev dependency of apps/server). Writes images/ and images/manifest.json (image_url -> file name).
JPEG and PNG are kept; anything else is converted to JPEG. Anything over 1600 px or 4.5 MB is downscaled
(WhatsApp's limit is 5 MB).
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "images"
MAX_SIDE = 1600
MAX_BYTES = 4_500_000
UA = "yyai-demo-image-fetch/1.0 (client catalogue images)"


def normalise(raw: bytes) -> tuple[bytes, str]:
    img = Image.open(io.BytesIO(raw))
    fmt = (img.format or "").upper()
    if fmt in ("JPEG", "PNG") and max(img.size) <= MAX_SIDE and len(raw) <= MAX_BYTES:
        return raw, "jpg" if fmt == "JPEG" else "png"
    keep_png = fmt == "PNG"
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    if keep_png and img.mode in ("RGBA", "LA", "P", "RGB"):
        img.save(out, "PNG", optimize=True)
        if out.tell() <= MAX_BYTES:
            return out.getvalue(), "png"
        out = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.split()[3])
        img = flat
    img.convert("RGB").save(out, "JPEG", quality=88)
    return out.getvalue(), "jpg"


def main() -> int:
    items = json.loads((HERE / "catalogue.json").read_text())["items"]
    urls = sorted({i["image_url"] for i in items if i.get("image_url")})
    OUT.mkdir(exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest: dict[str, str] = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    downloaded = skipped = 0
    failures: list[tuple[str, str]] = []
    for url in urls:
        if url in manifest and (OUT / manifest[url]).exists():
            skipped += 1
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            data, ext = normalise(raw)
            name = f"{hashlib.sha1(url.encode()).hexdigest()}.{ext}"
            (OUT / name).write_bytes(data)
            manifest[url] = name
            downloaded += 1
        except Exception as exc:  # noqa: BLE001 - report and carry on
            failures.append((url, repr(exc)))
        time.sleep(0.3)
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"distinct urls {len(urls)}, downloaded {downloaded}, skipped {skipped}, failed {len(failures)}")
    for url, err in failures:
        print("FAIL", url, err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
