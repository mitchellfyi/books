"""Apply exact, language-specific pronunciation entries before TTS."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable


def pronunciation_terms_in_text(text: str, lang: str, entries: list[dict]) -> list[str]:
    """Return the canonical dictionary terms that would affect this text."""
    candidates: list[tuple[str, dict]] = []
    for entry in entries:
        if lang not in entry.get("phonemes", {}):
            continue
        for spelling in (entry["term"], *entry.get("aliases", [])):
            candidates.append((spelling, entry))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (-len(item[0]), item[0].casefold()))
    alternatives = "|".join(re.escape(spelling) for spelling, _entry in candidates)
    pattern = re.compile(rf"(?<!\w)({alternatives})(?!\w)", re.IGNORECASE)
    lookup: dict[str, dict] = {}
    for spelling, entry in candidates:
        lookup.setdefault(spelling.casefold(), entry)

    used: set[str] = set()
    for match in pattern.finditer(text):
        entry = lookup[match.group(0).casefold()]
        if entry.get("case_sensitive") and match.group(0) not in {
            entry["term"], *entry.get("aliases", [])
        }:
            continue
        used.add(entry["term"])
    return sorted(used, key=str.casefold)


def dictionary_affects_script(script_text: str, sidecar: dict, entries: list[dict]) -> bool:
    """A pronunciation-dictionary change only stales audio it could actually alter.

    Stale when the sidecar recorded applied terms (their entries may have
    changed or gone), or when any current entry's spelling appears in the
    script for the sidecar's language. Otherwise the regenerated audio would
    be byte-identical in pronunciation, so the old file stays fresh.
    """
    if sidecar.get("pronunciation_terms"):
        return True
    lang = sidecar.get("lang", "")
    for entry in entries:
        if lang not in entry.get("phonemes", {}):
            continue
        for spelling in (entry["term"], *entry.get("aliases", [])):
            if re.search(rf"(?<!\w){re.escape(spelling)}(?!\w)", script_text, re.IGNORECASE):
                return True
    return False


def pronunciation_is_current(script_text: str, sidecar: dict, entries: list[dict]) -> bool:
    """Compare only the pronunciation entries that can change this narration."""
    lang = sidecar.get("lang", "")
    current_terms = pronunciation_terms_in_text(script_text, lang, entries)
    previous_terms = sidecar.get("pronunciation_terms", [])
    previous_signature = sidecar.get("pronunciation_entries_sha256")
    if previous_signature:
        return (
            current_terms == previous_terms
            and pronunciation_signature(current_terms, lang, entries) == previous_signature
        )
    return not dictionary_affects_script(script_text, sidecar, entries)


def pronunciation_signature(terms: list[str], lang: str, entries: list[dict]) -> str:
    """Hash only the language-specific entries used by one narration."""
    by_term = {entry["term"]: entry for entry in entries}
    selected: list[dict] = []
    for term in sorted(terms, key=str.casefold):
        entry = by_term.get(term)
        if entry is None or lang not in entry.get("phonemes", {}):
            selected.append({"term": term, "missing": True})
            continue
        selected.append({
            "term": entry["term"],
            "aliases": entry.get("aliases", []),
            "case_sensitive": entry.get("case_sensitive", False),
            "phonemes": entry["phonemes"][lang],
        })
    payload = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


SIBILANTS = ("tʃ", "dʒ", "s", "z", "ʃ", "ʒ")
VOICELESS = ("p", "t", "k", "f", "θ")


def possessive_suffix(phonemes: str) -> str:
    """The English possessive ending that follows these phonemes.

    Without this, a dictionary term swallows the name and leaves a bare "'s"
    to be phonemised alone, which Kokoro reads as the letter: "Proust ess".
    """
    tail = phonemes.rstrip("ˈˌː ")
    if tail.endswith(SIBILANTS):
        return "ɪz"
    return "s" if tail.endswith(VOICELESS) else "z"


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
    # A trailing possessive is part of the match: left behind, it is phonemised
    # on its own and spoken as the letter "ess".
    pattern = re.compile(rf"(?<!\w)({alternatives})(['’]s)?(?!\w)", re.IGNORECASE)
    lookup: dict[str, dict] = {}
    for spelling, entry in candidates:
        lookup.setdefault(spelling.casefold(), entry)

    pieces: list[str] = []
    used: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        spelling, possessive = match.group(1), match.group(2)
        entry = lookup[spelling.casefold()]
        if entry.get("case_sensitive") and spelling not in {
            entry["term"], *entry.get("aliases", [])
        }:
            continue
        if match.start() > cursor:
            normal = phonemize(text[cursor:match.start()], lang).strip()
            if normal:
                pieces.append(normal)
        custom = entry["phonemes"][lang].strip()
        if possessive:
            custom += possessive_suffix(custom)
        # Validate what is actually sent to the model, suffix included.
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
