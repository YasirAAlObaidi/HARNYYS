"""Turn the model's markdown into WhatsApp's own formatting. Pure functions.

WhatsApp: *bold*, _italic_, ~strike~. Markdown: **bold**, __bold__, # Heading, [text](url).
"""

from __future__ import annotations

import re

_LINK = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)\s*\)")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$")
_DUNDER = re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")


def to_whatsapp(text: str) -> str:
    return "\n".join(_line(line) for line in text.split("\n"))


def _line(line: str) -> str:
    line = _LINK.sub(_link, line)
    heading = _HEADING.match(line)
    if heading:
        inner = heading.group(1).replace("**", "").replace("__", "").replace("*", "").strip()
        return f"*{inner}*" if inner else ""
    line = _bold(line)
    line = _DUNDER.sub(lambda m: f"*{m.group(1).strip()}*", line)
    return _STRIKE.sub(lambda m: f"~{m.group(1)}~", line)


def _link(match: re.Match[str]) -> str:
    label, url = match.group(1).strip(), match.group(2)
    return url if label == url else f"{label}: {url}"


def _bold(line: str) -> str:
    """Pair the ** markers left to right. An unpaired one is dropped, so no stray ** is ever sent."""
    parts = line.split("**")
    out = []
    for i, part in enumerate(parts):
        closed = i % 2 == 1 and i < len(parts) - 1  # odd pieces sit between an opening and a closing marker
        if not closed:
            out.append(part)
            continue
        inner = part.strip()
        if inner:
            lead, trail = part[: len(part) - len(part.lstrip())], part[len(part.rstrip()) :]
            out.append(f"{lead}*{inner}*{trail}")
    return "".join(out)
