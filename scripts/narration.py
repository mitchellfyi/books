"""Parse narration scripts: flat front matter, body text, and spoken word counts."""

from __future__ import annotations

import re
from pathlib import Path


def parse_front_matter(path: Path) -> tuple[dict, str]:
    """Return (front matter dict, body). Front matter is flat `key: value` lines."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, object] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip("'\"")
        if value in ("true", "false"):
            meta[key.strip()] = value == "true"
        elif value.isdigit():
            meta[key.strip()] = int(value)
        else:
            meta[key.strip()] = value
    return meta, text[end + 5:].strip()


def word_count(body: str) -> int:
    """Count words as narration: markdown syntax stripped, URLs excluded."""
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)  # links -> text
    body = re.sub(r"^#+\s*", "", body, flags=re.M)
    body = re.sub(r"[*_`>#]", "", body)
    return len(body.split())
