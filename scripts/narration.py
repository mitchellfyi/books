"""Narration scripts: front matter, the spoken text, word counts, and synthesis chunks.

Everything here works on plain strings so the rules that decide what a
narrator says stay testable without the text-to-speech dependencies.
"""

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


def spoken_text(body: str) -> str:
    """The words a narrator actually says: markdown syntax stripped, URLs dropped.

    One definition serves the whole pipeline — the word counts `check`
    enforces, the terms the pronunciation dictionary is matched against, and
    the text sent to the synthesiser — so a script cannot pass its target on
    characters nobody hears.
    """
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)  # links -> their text
    body = re.sub(r"^#+\s*", "", body, flags=re.M)  # heading markers
    body = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", body, flags=re.M)  # list markers
    body = re.sub(r"[*_`>#]", "", body)  # inline emphasis and quoting
    return re.sub(r"[ \t]+", " ", body).strip()


def word_count(body: str) -> int:
    """Count the words a narrator would speak."""
    return len(spoken_text(body).split())


def chunked_paragraphs(text: str, max_chars: int = 350) -> list[list[str]]:
    """Sentence-packed chunks per paragraph, kept below the model's comfort limit."""
    paragraphs = [p.strip().replace("\n", " ") for p in re.split(r"\n\s*\n", text) if p.strip()]
    result = []
    for paragraph in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        result.append(chunks)
    return result
