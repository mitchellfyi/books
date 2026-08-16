#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.21"]
# ///
"""Validate the whole library: schemas, cross-references, word counts, audio freshness.

Usage:
    uv run scripts/check.py            # full report + status table
    uv run scripts/check.py --quiet    # errors and warnings only
    uv run scripts/check.py <book-id>  # limit book-level checks to one book

Exit code 1 on errors, 0 otherwise (warnings do not fail the run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from narration import parse_front_matter, spoken_text, word_count
from pronunciation import pronunciation_is_current
from rating import rating_errors, rubric_errors

ROOT = Path(__file__).resolve().parent.parent

errors: list[str] = []
warnings: list[str] = []

NARRATION_META_PATTERNS = {
    r"\bthis (?:brief|summary|transcript)\b": "announces the summary",
    r"\b(?:as |within )?this library\b": "mentions the product instead of the book",
    r"\belsewhere on (?:these|the) shelves\b": "mentions the product instead of the book",
    r"\b(?:the )?rubric(?: excludes| includes| scores| weights)?\b": "describes internal scoring mechanics",
    r"\bover the next\b": "announces the running time",
    r"\byou will hear\b": "announces what the narration will do",
    r"\b(?:coverage note|quality review|workflow status|research process|production process)\b": "mentions internal process metadata",
    r"\b(?:sources?|citations?) (?:used|consulted|for this)\b": "describes research provenance",
    r"\b(?:based|researched|sourced|compiled) (?:on|from) (?:the )?(?:publisher|sources?|reviews?|interviews?)\b": "describes research provenance",
    r"\bnot (?:been )?checked against (?:a )?full (?:copy|book|text)\b": "describes research coverage",
    r"https?://": "contains a raw URL",
}

# The research floors AGENTS.md states, named so a message cannot go on
# quoting a number the check no longer uses.
MINIMUM_BOOK_SOURCES = 6
MINIMUM_RECEPTION_SOURCES = 2
MINIMUM_AUTHOR_SOURCES = 3
RECEPTION_TYPES = {"professional-review", "specialist-review"}

# docs/review-method.md defines these eight and what each one attests to.
REQUIRED_QUALITY_CHECKS = {
    "identity_and_metadata", "content_fidelity", "claim_support", "counterevidence",
    "citation_entailment", "product_fit", "plain_language", "audio_pronunciation",
}


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(f"{rel(path)}: file missing")
    except json.JSONDecodeError as exc:
        err(f"{rel(path)}: invalid JSON ({exc})")
    return None


@lru_cache(maxsize=None)
def load_json_once(path: Path) -> dict | None:
    """Read a library document once per run, whichever check asks first.

    Several checks reach for the same book.json — the book pass, the queue
    pass, a relationship source_ref — so this both saves the re-reads and
    keeps a broken file from being reported once per reader.
    """
    return load_json(path)


def library_dirs(folder: str) -> list[Path]:
    """The entity directories under a library folder, sorted, or none at all.

    A repository without books yet is a valid one to validate, so an absent
    folder is emptiness rather than a crash.
    """
    base = ROOT / folder
    return sorted(d for d in base.iterdir() if d.is_dir()) if base.is_dir() else []


def duplicates(values: list) -> list:
    """The values appearing more than once, in a stable reported order."""
    seen: set = set()
    repeated: dict = {}
    for value in values:
        if value in seen:
            repeated[value] = None
        seen.add(value)
    return list(repeated)


@lru_cache(maxsize=None)
def schema_validator(schema_name: str) -> Draft202012Validator:
    """Compile each schema once; a full run validates ~200 documents against nine."""
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_schema(doc: dict, schema_name: str, path: Path) -> bool:
    validator = schema_validator(schema_name)
    ok = True
    # Editors validate as you type from this pointer, and it is relative, so
    # moving a file to another depth breaks it silently. We already know which
    # schema this document must satisfy: check the pointer agrees.
    pointer = doc.get("$schema", "")
    if pointer and not pointer.startswith("http"):
        if (path.parent / pointer).resolve() != (ROOT / "schemas" / schema_name).resolve():
            err(f"{rel(path)}: $schema '{pointer}' does not resolve to schemas/{schema_name}")
            ok = False
    for e in validator.iter_errors(doc):
        loc = "/" + "/".join(str(p) for p in e.absolute_path)
        err(f"{rel(path)}: schema violation at {loc}: {e.message}")
        ok = False
    return ok


def resolve_pointer(doc: dict, pointer: str) -> bool:
    node: object = doc
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return False
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return False
            node = node[int(token)]
        else:
            return False
    return True


def has_inline_sources(doc: dict, pointer: str) -> bool:
    """True if the field at pointer (or its items) carries its own source_ids."""
    node: object = doc
    for token in pointer.lstrip("/").split("/"):
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return False
    if isinstance(node, dict):
        return "source_ids" in node
    if isinstance(node, list):
        return all(isinstance(i, dict) and "source_ids" in i for i in node) and bool(node)
    return False


def check_source_ids(doc: dict, path: Path, known: set, *,
                     require_sources: bool, skip: str | None = None) -> None:
    """Report every source_ids list that is empty or names a source we lack.

    `known` is the pool a reference may draw on — a document's own sources for
    book.json and author.json, the book's for content.json, which is why the
    pool is passed in rather than read here. `skip` names the branch that
    defines those sources instead of citing them.
    """
    def walk(node: object, trail: str) -> None:
        if isinstance(node, dict):
            if "source_ids" in node:
                if require_sources and not node["source_ids"]:
                    err(f"{rel(path)}: {trail or '/'} has no supporting sources")
                for source_id in node["source_ids"]:
                    if source_id not in known:
                        err(f"{rel(path)}: {trail or '/'} cites unknown source '{source_id}'")
            for key, value in node.items():
                if key != skip:
                    walk(value, f"{trail}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{trail}/{index}")

    walk(doc, "")


def check_research(doc: dict, path: Path) -> None:
    """A document's own research block: unique ids, live pointers, resolvable refs."""
    ids = [s["id"] for s in doc.get("research", {}).get("sources", [])]
    for dup in duplicates(ids):
        err(f"{rel(path)}: duplicate source id '{dup}'")
    known = set(ids)
    check_source_ids(doc, path, known, skip="research",
                     require_sources=doc.get("workflow", {}).get("status") != "stub")

    for pointer, source_ids in doc.get("research", {}).get("citations", {}).items():
        if not resolve_pointer(doc, pointer):
            err(f"{rel(path)}: citation pointer '{pointer}' does not resolve")
        elif has_inline_sources(doc, pointer):
            warn(
                f"{rel(path)}: citation map entry '{pointer}' duplicates inline source_ids; "
                "keep the inline ones and drop the map entry"
            )
        for source_id in source_ids:
            if source_id not in known:
                err(f"{rel(path)}: citations['{pointer}'] cites unknown source '{source_id}'")


def check_configs(audio_cfg: dict, pronunciations_cfg: dict, pronunciations_path: Path,
                  rating_cfg: dict, tags_doc: dict) -> str:
    """Validate the shared configuration. Returns the pronunciation-file hash."""
    validate_schema(audio_cfg, "audio-config.schema.json", ROOT / "config/audio.json")
    validate_schema(pronunciations_cfg, "pronunciations.schema.json", pronunciations_path)
    validate_schema(rating_cfg, "rating-config.schema.json", ROOT / "config/rating.json")
    for problem in rubric_errors(rating_cfg):
        err(f"config/rating.json: {problem}")
    validate_schema(tags_doc, "tags.schema.json", ROOT / "taxonomy/tags.json")

    if ROOT / audio_cfg["tts"]["pronunciation_dictionary"] != pronunciations_path:
        err("config/audio.json: pronunciation_dictionary must point to config/pronunciations.json")

    # Defaults that name something the same file does not offer fail silently:
    # the player falls back to its first option, and the generator to whatever
    # voice it can find, with nothing said either way.
    speeds = audio_cfg["playback_speeds"]
    if audio_cfg.get("default_playback_speed") not in speeds:
        err(f"config/audio.json: default_playback_speed "
            f"{audio_cfg.get('default_playback_speed')} is not one of playback_speeds "
            f"({', '.join(str(speed) for speed in speeds)})")
    voices = audio_cfg["tts"].get("voices", {})
    if voices and audio_cfg["tts"]["default_voice"] not in voices:
        err(f"config/audio.json: default_voice '{audio_cfg['tts']['default_voice']}' "
            "is not listed in tts.voices")

    # Which entry claimed each spelling, so a collision names both entries.
    # Two entries can share a spelling exactly, and "'X' collides with 'X'"
    # left the reader searching a 38-entry file for the other one.
    claimed_by: dict[str, str] = {}
    for entry in pronunciations_cfg["entries"]:
        for spelling in (entry["term"], *entry["aliases"]):
            folded = spelling.casefold()
            if folded in claimed_by:
                err(f"config/pronunciations.json: spelling '{spelling}' in entry "
                    f"'{entry['term']}' is already claimed by entry '{claimed_by[folded]}'")
            claimed_by[folded] = entry["term"]
        # The entry's phonemes replace everything its spelling matched, so an
        # alias that adds words drops them from the narration: aliasing
        # 'Sloterdijk' to 'Peter Sloterdijk' voiced it without the 'Peter'.
        for alias in entry["aliases"]:
            if len(alias.split()) > len(entry["term"].split()):
                err(
                    f"config/pronunciations.json: alias '{alias}' has more words than "
                    f"term '{entry['term']}', so its phonemes cannot cover them; give the "
                    "longer form its own entry with complete phonemes"
                )

    tag_ids = {t["id"] for t in tags_doc["tags"]}
    for alias in (a for t in tags_doc["tags"] for a in t["aliases"]):
        if alias in tag_ids:
            err(f"taxonomy/tags.json: alias '{alias}' collides with a canonical tag id")

    return hashlib.sha256(pronunciations_path.read_bytes()).hexdigest()


def check_catalog(catalog: dict) -> dict:
    """Validate the catalogue against the library on disk. Returns entities by id."""
    validate_schema(catalog, "catalog.schema.json", ROOT / "data/catalog.json")
    for duplicate in duplicates([e["id"] for e in catalog["entities"]]):
        err(f"data/catalog.json: duplicate entity id '{duplicate}'")
    entities = {e["id"]: e for e in catalog["entities"]}
    for e in catalog["entities"]:
        if e["state"] != "catalogued":
            continue
        if "path" not in e:
            err(f"data/catalog.json: catalogued entity '{e['id']}' has no path")
        elif not (ROOT / e["path"]).exists():
            err(f"data/catalog.json: path for '{e['id']}' does not exist: {e['path']}")

    for kind, folder in (("book", "library/books"), ("author", "library/authors")):
        for d in library_dirs(folder):
            if d.name not in entities:
                err(f"{rel(d)}: directory has no catalog entry")
            elif entities[d.name]["kind"] != kind:
                err(f"{rel(d)}: catalog entry kind mismatch")
    return entities


def check_relationships(relationships: dict, entities: dict) -> None:
    validate_schema(relationships, "relationships.schema.json", ROOT / "data/relationships.json")
    for duplicate in duplicates([r["id"] for r in relationships["relationships"]]):
        err(f"data/relationships.json: duplicate relationship id '{duplicate}'")
    for r in relationships["relationships"]:
        # Deduplicated: an edge with the same id at both ends said it twice.
        for endpoint in dict.fromkeys((r["source_id"], r["target_id"])):
            if endpoint not in entities:
                err(f"data/relationships.json: '{r['id']}' references unknown entity '{endpoint}'")
        if r["source_id"] == r["target_id"]:
            err(f"data/relationships.json: '{r['id']}' links '{r['source_id']}' to itself")
        if r["basis"] == "explicit" and not r["source_refs"]:
            warn(f"data/relationships.json: '{r['id']}' is explicit but has no source_refs")
        for ref in r["source_refs"]:
            file_part, _, fragment = ref.partition("#")
            ref_path = ROOT / file_part
            if not ref_path.exists():
                err(f"data/relationships.json: '{r['id']}' source_ref file missing: {file_part}")
                continue
            # 118 refs across 32 files, so read each once. A file that will
            # not parse is reported by load_json, not called missing here.
            ref_doc = load_json_once(ref_path)
            if ref_doc is None:
                continue
            if fragment and fragment not in {
                s["id"] for s in ref_doc.get("research", {}).get("sources", [])
            }:
                err(f"data/relationships.json: '{r['id']}' source_ref '#{fragment}' "
                    f"not found in {file_part}")


def check_authors() -> None:
    for d in library_dirs("library/authors"):
        doc = load_json_once(d / "author.json")
        if not doc:
            continue
        validate_schema(doc, "author.schema.json", d / "author.json")
        if doc.get("id") != d.name:
            err(f"{rel(d)}/author.json: id '{doc.get('id')}' does not match directory name")
        check_research(doc, d / "author.json")
        if doc.get("workflow", {}).get("status") != "stub" \
                and len(doc.get("research", {}).get("sources", [])) < MINIMUM_AUTHOR_SOURCES:
            warn(f"{rel(d)}/author.json: fewer than {MINIMUM_AUTHOR_SOURCES} "
                 "useful author sources")


def check_book_record(d: Path, doc: dict, entities: dict, tag_ids: set) -> None:
    """The book's own identity, links into the catalogue and taxonomy, and sources."""
    validate_schema(doc, "book.schema.json", d / "book.json")
    if doc.get("id") != d.name:
        err(f"{rel(d)}/book.json: id '{doc.get('id')}' does not match directory name")
    for aid in doc.get("author_ids", []):
        if aid not in entities or entities[aid]["kind"] != "author":
            err(f"{rel(d)}/book.json: unknown author id '{aid}'")
    for tid in doc.get("discovery", {}).get("tag_ids", []):
        if tid not in tag_ids:
            err(f"{rel(d)}/book.json: tag '{tid}' is not in taxonomy/tags.json")
    check_research(doc, d / "book.json")


def check_book_content(d: Path, doc: dict, rating_cfg: dict) -> dict | None:
    """The structured content and everything a 'complete' status promises."""
    content_path = d / "content.json"
    content = load_json_once(content_path) if content_path.exists() else None
    book_status = doc.get("workflow", {}).get("status")

    if content:
        validate_schema(content, "content.schema.json", content_path)
        if content.get("book_id") != d.name:
            err(f"{rel(content_path)}: book_id does not match directory name")
        if content.get("content_type") != "non-fiction":
            err(f"{rel(content_path)}: this library accepts non-fiction only")
        idea_ids = [i.get("id") for i in content.get("ideas", [])]
        for duplicate in duplicates(idea_ids):
            err(f"{rel(content_path)}: duplicate idea id '{duplicate}'")
        known_ideas = set(idea_ids)
        for section in content.get("book_map", []):
            for idea_id in section.get("idea_ids", []):
                if idea_id not in known_ideas:
                    # Named: several parts often cite one renamed idea, and
                    # identical lines leave the reader nothing to search for.
                    err(f"{rel(content_path)}: book_map part "
                        f"{section.get('order', '?')} cites unknown idea '{idea_id}'")
        # content.json interprets the book; its citations resolve against the
        # sources book.json records.
        content_researched = content.get("workflow", {}).get("status") != "stub"
        check_source_ids(
            content, content_path,
            {s["id"] for s in doc.get("research", {}).get("sources", [])},
            require_sources=content_researched,
        )
        orders = [section.get("order") for section in content.get("book_map", [])]
        if orders != list(range(1, len(orders) + 1)):
            err(f"{rel(content_path)}: book_map order must be consecutive from 1")
        rating = content.get("assessment", {}).get("rating")
        if content_researched or rating is not None:
            for problem in rating_errors(rating, rating_cfg,
                                         require_complete=content_researched):
                err(f"{rel(content_path)}: assessment.rating {problem}")
    elif book_status != "stub":
        err(f"{rel(content_path)}: researched books require structured content")

    coverage = doc.get("workflow", {}).get("coverage", "metadata-only")
    if content and content.get("workflow", {}).get("status") != book_status:
        err(f"{rel(content_path)}: workflow status differs from book.json")
    if content and content.get("workflow", {}).get("reviewed_against_full_book") \
            and coverage != "full-book":
        err(f"{rel(content_path)}: full-book review is true but book.json coverage is '{coverage}'")

    if book_status == "complete":
        # Coverage is recorded, not a gate (owner's decision): complete
        # profiles are allowed at any coverage, but the label must be true.
        sources = doc.get("research", {}).get("sources", [])
        if len(sources) < MINIMUM_BOOK_SOURCES:
            err(f"{rel(d)}/book.json: complete status requires at least "
                f"{MINIMUM_BOOK_SOURCES} useful sources")
        reception = [s for s in sources if s.get("independence") == "independent"
                     and s.get("type") in RECEPTION_TYPES]
        if len(reception) < MINIMUM_RECEPTION_SOURCES:
            err(f"{rel(d)}/book.json: complete status requires "
                f"{MINIMUM_RECEPTION_SOURCES} independent reception sources")
        review = (content or {}).get("workflow", {}).get("quality_review", {})
        if review.get("status") != "passed" or not review.get("reviewed_at"):
            err(f"{rel(content_path)}: complete status requires a dated, passed quality review")
        incomplete = [name for name, passed in review.get("checks", {}).items() if not passed]
        missing = REQUIRED_QUALITY_CHECKS - set(review.get("checks", {}))
        if incomplete or missing:
            names = sorted(set(incomplete) | missing)
            err(f"{rel(content_path)}: quality review checks not passed: {', '.join(names)}")
    return content


def check_script(d: Path, duration: str, audio_cfg: dict, entry: dict) -> str:
    """Validate one narration script. Returns the text a listener would hear."""
    path = d / "scripts" / f"{duration}.md"
    if not path.exists():
        return ""
    meta, body = parse_front_matter(path)
    entry["script"] = meta.get("status", "?")
    entry["words"] = word_count(body)
    if meta.get("book_id") != d.name:
        err(f"{rel(path)}: book_id front matter mismatch")
    if meta.get("duration") != duration:
        err(f"{rel(path)}: duration front matter does not match filename")
    if meta.get("source") != "content.json":
        err(f"{rel(path)}: source front matter must be 'content.json'")
    target = audio_cfg["levels"][duration]["target_words"]
    if meta.get("target_words") != target:
        err(f"{rel(path)}: target_words {meta.get('target_words')} != configured {target}")
    if meta.get("status") == "complete":
        tolerance = audio_cfg["word_count_tolerance_percent"] / 100
        if not target * (1 - tolerance) <= entry["words"] <= target * (1 + tolerance):
            err(f"{rel(path)}: {entry['words']} words is outside {target}±{tolerance:.0%}")
        for pattern, problem in NARRATION_META_PATTERNS.items():
            if re.search(pattern, body, flags=re.IGNORECASE):
                err(f"{rel(path)}: narration {problem}; keep research metadata out of audio")
    return spoken_text(body)


def check_audio(d: Path, duration: str, narration: str, audio_cfg: dict,
                pronunciations: list[dict], pronunciation_sha: str, entry: dict) -> None:
    """Audio and sidecar, one pair per voice: <level>.<voice>.<format> + .json.

    Freshness is judged from the sidecars, not the recordings. Sidecars are
    committed and recordings are not, so a script edited without regenerating
    is visible to anyone with the repository — a fresh clone, a CI runner —
    which is where that mistake most needs catching. The recordings then say
    only whether the audio is here.
    """
    script_path = d / "scripts" / f"{duration}.md"
    files = list((d / "audio").glob(f"{duration}.*")) if (d / "audio").exists() else []
    media = [a for a in files if a.suffix != ".json"]
    script_sha = hashlib.sha256(script_path.read_bytes()).hexdigest() \
        if script_path.exists() else None

    stale_voices: set[str] = set()
    for sidecar_path in sorted(a for a in files if a.suffix == ".json"):
        voice = sidecar_path.name.split(".")[1] if sidecar_path.name.count(".") == 2 else None
        sidecar = load_json(sidecar_path)
        if sidecar is None:
            continue
        validate_schema(sidecar, "audio-sidecar.schema.json", sidecar_path)
        if voice is not None and sidecar.get("voice") != voice:
            err(f"{rel(sidecar_path)}: sidecar voice '{sidecar.get('voice')}' "
                f"does not match filename voice '{voice}'")
        if sidecar.get("source_script_sha256") != script_sha:
            warn(f"{rel(sidecar_path)}: audio is stale (script changed since generation)")
            stale_voices.add(voice)
            entry["sidecar"] = "stale"
        elif sidecar.get("pronunciation_dictionary_sha256") != pronunciation_sha \
                and not pronunciation_is_current(narration, sidecar, pronunciations):
            warn(f"{rel(sidecar_path)}: audio is stale (pronunciation dictionary changed "
                 "for a term this script uses)")
            stale_voices.add(voice)
            entry["sidecar"] = "stale"
        else:
            entry["sidecar"] = entry["sidecar"] or "current"

    for audio_file in media:
        parts = audio_file.name.split(".")
        if len(parts) != 3:
            err(f"{rel(audio_file)}: audio files must be named <level>.<voice>.<format>")
            entry["audio"] = entry["audio"] or "fresh"
            continue
        voice = parts[1]
        if not (d / "audio" / f"{duration}.{voice}.json").exists():
            reporter = err if audio_cfg["tts"].get("metadata_sidecar_required") else warn
            reporter(f"{rel(audio_file)}: audio present without sidecar "
                     f"{duration}.{voice}.json")
            entry["audio"] = entry["audio"] or "fresh"
        elif voice in stale_voices:
            entry["audio"] = "stale"
        else:
            entry["audio"] = entry["audio"] or "fresh"


def check_required_levels(d: Path, durations: dict, levels: dict,
                          audio_expected: bool = True) -> None:
    """A complete book owes a complete script and current audio at every required level.

    Stale audio is always an error, and it is read from the sidecars, so it is
    caught with or without the recordings: a sidecar that disagrees with the
    script beside it is committed, portable and wrong. Absent audio is an error
    too, because the definition of done requires it — but only where the
    recordings could be. They are deliberately not committed, so a fresh clone
    and a CI runner have none, and `--no-local-audio` says so rather than
    reporting 31 books as broken.
    """
    required = [du for du in durations if levels[du]["required"]]
    missing_scripts = [du for du in required if durations[du]["script"] != "complete"]
    if missing_scripts:
        err(f"{rel(d)}/book.json: status 'complete' but scripts not complete: "
            f"{', '.join(missing_scripts)}")
    stale = [du for du in required if durations[du]["sidecar"] == "stale"]
    if stale:
        err(f"{rel(d)}/book.json: status 'complete' but local audio is stale: "
            f"{', '.join(stale)}")
    # A level already reported stale is being regenerated anyway; saying it is
    # also absent adds a line and no information.
    absent = [du for du in required
              if durations[du]["audio"] is None and durations[du]["sidecar"] != "stale"]
    if absent:
        report = err if audio_expected else warn
        report(f"{rel(d)}/book.json: status 'complete' but no local audio for "
               f"{', '.join(absent)}; generate it with ./bookflow audio {d.name}")


def check_unconfigured_levels(d: Path, levels: dict) -> None:
    """Report scripts and sidecars for a level config/audio.json no longer names.

    Renaming a level leaves the old files behind, and nothing else looks at
    them: every other check iterates the configured levels, so the leftovers
    are invisible — and would be voiced again if the name ever came back.
    """
    for path in sorted((d / "scripts").glob("*.md")):
        if path.stem not in levels:
            warn(f"{rel(path)}: '{path.stem}' is not a level in config/audio.json; "
                 "delete it or configure the level")
    for path in sorted((d / "audio").glob("*")):
        if path.name != ".gitkeep" and path.name.split(".")[0] not in levels:
            warn(f"{rel(path)}: '{path.name.split('.')[0]}' is not a level in "
                 "config/audio.json; delete it or configure the level")


def check_books(only: str | None, audio_cfg: dict, rating_cfg: dict,
                pronunciations: list[dict], pronunciation_sha: str,
                entities: dict, tag_ids: set, audio_expected: bool = True) -> dict:
    if only and not (ROOT / "library/books" / only).is_dir():
        err(f"no such book: {only}")
    status_rows: dict[str, dict] = {}
    for d in library_dirs("library/books"):
        if only and d.name != only:
            continue
        doc = load_json_once(d / "book.json")
        if not doc:
            continue
        check_book_record(d, doc, entities, tag_ids)
        check_book_content(d, doc, rating_cfg)
        check_unconfigured_levels(d, audio_cfg["levels"])

        durations: dict[str, dict] = {}
        for duration in audio_cfg["levels"]:
            entry = {"script": None, "words": None, "audio": None, "sidecar": None}
            narration = check_script(d, duration, audio_cfg, entry)
            check_audio(d, duration, narration, audio_cfg,
                        pronunciations, pronunciation_sha, entry)
            durations[duration] = entry
        status_rows[d.name] = {"book": doc, "durations": durations}

        if doc.get("workflow", {}).get("status") == "complete":
            check_required_levels(d, durations, audio_cfg["levels"], audio_expected)
    return status_rows


def check_playlists(audio_cfg: dict, entities: dict) -> None:
    path = ROOT / "data/playlists.json"
    if not path.exists():
        return
    doc = load_json(path)
    if doc is None:
        return
    validate_schema(doc, "playlists.schema.json", path)
    for duplicate in duplicates([p.get("id") for p in doc.get("playlists", [])]):
        err(f"data/playlists.json: duplicate playlist id '{duplicate}'")
    for playlist in doc.get("playlists", []):
        name = playlist.get("name")
        for item in playlist.get("items", []):
            if item["book_id"] not in entities:
                err(f"data/playlists.json: playlist '{name}' references unknown book "
                    f"'{item['book_id']}'")
            elif entities[item["book_id"]]["kind"] != "book":
                err(f"data/playlists.json: playlist '{name}' item is not a book")
            if item["duration"] not in audio_cfg["levels"]:
                err(f"data/playlists.json: playlist '{name}' has unknown duration "
                    f"'{item['duration']}'")
        for duplicate in duplicates([item["book_id"] for item in playlist.get("items", [])]):
            warn(f"data/playlists.json: playlist '{name}' lists '{duplicate}' "
                 "at more than one duration; playlists should hold one entry per book")


def check_queue(entities: dict) -> None:
    path = ROOT / "data/queue.json"
    if not path.exists():
        return
    doc = load_json(path)
    if doc is None:
        return
    validate_schema(doc, "queue.schema.json", path)
    for duplicate in duplicates([item["book_id"] for item in doc.get("queue", [])]):
        err(f"data/queue.json: '{duplicate}' is queued more than once")
    for duplicate in duplicates([item["priority"] for item in doc.get("queue", [])]):
        warn(f"data/queue.json: priority {duplicate} is used more than once; order is ambiguous")
    for item in doc.get("queue", []):
        if item["book_id"] not in entities or entities[item["book_id"]]["kind"] != "book":
            err(f"data/queue.json: unknown book '{item['book_id']}'")
            continue
        book_path = ROOT / "library/books" / item["book_id"] / "book.json"
        book_doc = load_json_once(book_path) if book_path.exists() else None
        book_status = (book_doc or {}).get("workflow", {}).get("status")
        if item["status"] == "done" and book_status != "complete":
            warn(f"data/queue.json: '{item['book_id']}' is marked done but book.json "
                 f"status is '{book_status}'")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check.py",
        description="Validate the library: schemas, cross-references, word counts, audio freshness.",
        epilog="Exit code 1 on errors; warnings do not fail the run.",
    )
    parser.add_argument("book_id", nargs="?", help="limit book-level checks to one book")
    parser.add_argument("--quiet", action="store_true", help="show only warnings and errors")
    parser.add_argument(
        "--no-local-audio", action="store_true",
        help="this machine has no generated audio, so report its absence as a warning "
             "rather than an error (audio is not committed: use this on a fresh clone "
             "or in CI). Audio that is present but stale is still an error.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    pronunciations_path = ROOT / "config/pronunciations.json"
    audio_cfg = load_json(ROOT / "config/audio.json")
    pronunciations_cfg = load_json(pronunciations_path)
    rating_cfg = load_json(ROOT / "config/rating.json")
    tags_doc = load_json(ROOT / "taxonomy/tags.json")
    catalog = load_json(ROOT / "data/catalog.json")
    relationships = load_json(ROOT / "data/relationships.json")
    # Every later check reads one of these, so a missing or broken one ends
    # the run rather than producing a page of consequential errors.
    if not all([audio_cfg, pronunciations_cfg, rating_cfg, tags_doc, catalog, relationships]):
        return report(args.quiet, {}, [])

    pronunciation_sha = check_configs(
        audio_cfg, pronunciations_cfg, pronunciations_path, rating_cfg, tags_doc)
    entities = check_catalog(catalog)
    check_relationships(relationships, entities)
    check_authors()
    status_rows = check_books(
        args.book_id, audio_cfg, rating_cfg, pronunciations_cfg["entries"],
        pronunciation_sha, entities, {t["id"] for t in tags_doc["tags"]},
        audio_expected=not args.no_local_audio)
    check_playlists(audio_cfg, entities)
    check_queue(entities)
    return report(args.quiet, status_rows, list(audio_cfg["levels"]))


def report(quiet: bool, status_rows: dict, durations: list[str]) -> int:
    if not quiet and status_rows:
        print("Library status")
        print(f"  {'book':40} {'status':20} {'coverage':22} "
              + " ".join(f"{d:>12}" for d in durations))
        for book_id, row in status_rows.items():
            wf = row["book"].get("workflow", {})
            cells = []
            for duration in durations:
                e = row["durations"][duration]
                script = {"complete": "script", None: "-"}.get(e["script"], str(e["script"]))
                audio = {"fresh": "+audio", "stale": "+STALE", None: ""}[e["audio"]]
                cells.append(f"{script}{audio:>6}" if audio else f"{script:>7}")
            print(f"  {book_id:40} {wf.get('status', '?'):20} {wf.get('coverage', '?'):22} "
                  + " ".join(f"{c:>12}" for c in cells))
        print()
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
