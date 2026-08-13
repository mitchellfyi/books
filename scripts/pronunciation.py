"""Apply exact, language-specific pronunciation entries before TTS."""

from __future__ import annotations

import re
from collections.abc import Callable


def phonemize_with_dictionary(
    text: str,
    lang: str,
    entries: list[dict],
    phonemize: Callable[[str, str], str],
    valid_symbols: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Return phonemes and canonical dictionary terms used in the text."""
    candidates: list[tuple[str, dict]] = []
    for entry in entries:
        if lang not in entry.get("phonemes", {}):
            continue
        for spelling in (entry["term"], *entry.get("aliases", [])):
            candidates.append((spelling, entry))
    if not candidates:
        return phonemize(text, lang), []

    # Longest spelling wins when a full name and one of its parts both exist.
    candidates.sort(key=lambda item: (-len(item[0]), item[0].casefold()))
    alternatives = "|".join(re.escape(item[0]) for item in candidates)
    pattern = re.compile(rf"(?<!\w)({alternatives})(?!\w)", re.IGNORECASE)
    lookup: dict[str, dict] = {}
    for spelling, entry in candidates:
        lookup.setdefault(spelling.casefold(), entry)

    pieces: list[str] = []
    used: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        entry = lookup[match.group(0).casefold()]
        if entry.get("case_sensitive") and match.group(0) not in {
            entry["term"], *entry.get("aliases", [])
        }:
            continue
        if match.start() > cursor:
            normal = phonemize(text[cursor:match.start()], lang).strip()
            if normal:
                pieces.append(normal)
        custom = entry["phonemes"][lang].strip()
        if valid_symbols is not None:
            invalid = sorted(set(custom) - valid_symbols)
            if invalid:
                rendered = " ".join(repr(item) for item in invalid)
                raise ValueError(f"pronunciation for '{entry['term']}' has unsupported symbols: {rendered}")
        pieces.append(custom)
        used.append(entry["term"])
        cursor = match.end()

    if cursor == 0:
        return phonemize(text, lang), []
    if cursor < len(text):
        normal = phonemize(text[cursor:], lang).strip()
        if normal:
            pieces.append(normal)
    return " ".join(pieces), sorted(set(used), key=str.casefold)
