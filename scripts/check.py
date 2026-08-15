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
    """load_json for documents several checks reach for, read once per run."""
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check.py",
        description="Validate the library: schemas, cross-references, word counts, audio freshness.",
        epilog="Exit code 1 on errors; warnings do not fail the run.",
    )
    parser.add_argument("book_id", nargs="?", help="limit book-level checks to one book")
    parser.add_argument("--quiet", action="store_true", help="show only warnings and errors")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    quiet, only = args.quiet, args.book_id

    # --- shared files ---
    audio_cfg = load_json(ROOT / "config/audio.json")
    pronunciations_path = ROOT / "config/pronunciations.json"
    pronunciations_cfg = load_json(pronunciations_path)
    rating_cfg = load_json(ROOT / "config/rating.json")
    tags_doc = load_json(ROOT / "taxonomy/tags.json")
    catalog = load_json(ROOT / "data/catalog.json")
    relationships = load_json(ROOT / "data/relationships.json")
    if not all([
        audio_cfg, pronunciations_cfg, rating_cfg, tags_doc, catalog, relationships,
    ]):
        return report(quiet, {}, [])

    validate_schema(audio_cfg, "audio-config.schema.json", ROOT / "config/audio.json")
    validate_schema(pronunciations_cfg, "pronunciations.schema.json", pronunciations_path)
    validate_schema(rating_cfg, "rating-config.schema.json", ROOT / "config/rating.json")
    for problem in rubric_errors(rating_cfg):
        err(f"config/rating.json: {problem}")
    validate_schema(tags_doc, "tags.schema.json", ROOT / "taxonomy/tags.json")
    validate_schema(catalog, "catalog.schema.json", ROOT / "data/catalog.json")
    validate_schema(relationships, "relationships.schema.json", ROOT / "data/relationships.json")

    configured_pronunciation_path = ROOT / audio_cfg["tts"]["pronunciation_dictionary"]
    if configured_pronunciation_path != pronunciations_path:
        err("config/audio.json: pronunciation_dictionary must point to config/pronunciations.json")
    pronunciation_sha = hashlib.sha256(pronunciations_path.read_bytes()).hexdigest()
    spellings: dict[str, str] = {}
    for entry in pronunciations_cfg["entries"]:
        for spelling in (entry["term"], *entry["aliases"]):
            folded = spelling.casefold()
            if folded in spellings:
                err(
                    "config/pronunciations.json: spelling "
                    f"'{spelling}' collides with '{spellings[folded]}'"
                )
            spellings[folded] = spelling
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
    tag_aliases = [a for t in tags_doc["tags"] for a in t["aliases"]]
    for alias in tag_aliases:
        if alias in tag_ids:
            err(f"taxonomy/tags.json: alias '{alias}' collides with a canonical tag id")

    entities = {e["id"]: e for e in catalog["entities"]}
    if len(entities) != len(catalog["entities"]):
        seen: set[str] = set()
        for e in catalog["entities"]:
            if e["id"] in seen:
                err(f"data/catalog.json: duplicate entity id '{e['id']}'")
            seen.add(e["id"])
    for e in catalog["entities"]:
        if e["state"] == "catalogued":
            if "path" not in e:
                err(f"data/catalog.json: catalogued entity '{e['id']}' has no path")
            elif not (ROOT / e["path"]).exists():
                err(f"data/catalog.json: path for '{e['id']}' does not exist: {e['path']}")

    # library dirs must be catalogued
    for kind, folder in (("book", "library/books"), ("author", "library/authors")):
        for d in library_dirs(folder):
            if d.name not in entities:
                err(f"{rel(d)}: directory has no catalog entry")
            elif entities[d.name]["kind"] != kind:
                err(f"{rel(d)}: catalog entry kind mismatch")

    # --- relationships ---
    rel_ids = [r["id"] for r in relationships["relationships"]]
    for dup in duplicates(rel_ids):
        err(f"data/relationships.json: duplicate relationship id '{dup}'")
    for r in relationships["relationships"]:
        for endpoint in (r["source_id"], r["target_id"]):
            if endpoint not in entities:
                err(f"data/relationships.json: '{r['id']}' references unknown entity '{endpoint}'")
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
                err(f"data/relationships.json: '{r['id']}' source_ref '#{fragment}' not found in {file_part}")

    # --- authors ---
    for d in library_dirs("library/authors"):
        doc = load_json(d / "author.json")
        if not doc:
            continue
        validate_schema(doc, "author.schema.json", d / "author.json")
        if doc.get("id") != d.name:
            err(f"{rel(d)}/author.json: id '{doc.get('id')}' does not match directory name")
        check_research(doc, d / "author.json")
        if doc.get("workflow", {}).get("status") != "stub" \
                and len(doc.get("research", {}).get("sources", [])) < 3:
            warn(f"{rel(d)}/author.json: fewer than three useful author sources")

    # --- books ---
    if only and not (ROOT / "library/books" / only).is_dir():
        err(f"no such book: {only}")
    levels = audio_cfg["levels"]
    durations = list(levels)
    tolerance = audio_cfg["word_count_tolerance_percent"] / 100
    status_rows: dict[str, dict] = {}

    for d in library_dirs("library/books"):
        if only and d.name != only:
            continue
        doc = load_json(d / "book.json")
        if not doc:
            continue
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

        content_path = d / "content.json"
        content = load_json(content_path)
        if content:
            validate_schema(content, "content.schema.json", content_path)
            if content.get("book_id") != d.name:
                err(f"{rel(content_path)}: book_id does not match directory name")
            if content.get("content_type") != "non-fiction":
                err(f"{rel(content_path)}: this library accepts non-fiction only")
            idea_ids = [i.get("id") for i in content.get("ideas", [])]
            for dup in duplicates(idea_ids):
                err(f"{rel(content_path)}: duplicate idea id '{dup}'")
            known_ideas = set(idea_ids)
            for section in content.get("book_map", []):
                for idea_id in section.get("idea_ids", []):
                    if idea_id not in known_ideas:
                        err(f"{rel(content_path)}: book_map cites unknown idea '{idea_id}'")
            # content.json interprets the book; its citations resolve against
            # the sources book.json records.
            check_source_ids(
                content, content_path,
                {s["id"] for s in doc.get("research", {}).get("sources", [])},
                require_sources=content.get("workflow", {}).get("status") != "stub",
            )
            orders = [section.get("order") for section in content.get("book_map", [])]
            if orders != list(range(1, len(orders) + 1)):
                err(f"{rel(content_path)}: book_map order must be consecutive from 1")
            rating = content.get("assessment", {}).get("rating")
            if content.get("workflow", {}).get("status") != "stub" or rating is not None:
                for problem in rating_errors(
                    rating,
                    rating_cfg,
                    require_complete=content.get("workflow", {}).get("status") != "stub",
                ):
                    err(f"{rel(content_path)}: assessment.rating {problem}")
        elif doc.get("workflow", {}).get("status") != "stub":
            err(f"{rel(content_path)}: researched books require structured content")

        wf = doc.get("workflow", {})
        coverage = wf.get("coverage", "metadata-only")
        if content and content.get("workflow", {}).get("status") != wf.get("status"):
            err(f"{rel(content_path)}: workflow status differs from book.json")
        if content and content.get("workflow", {}).get("reviewed_against_full_book") and coverage != "full-book":
            err(f"{rel(content_path)}: full-book review is true but book.json coverage is '{coverage}'")
        if wf.get("status") == "complete":
            # Coverage is recorded, not a gate (owner's decision): complete
            # profiles are allowed at any coverage, but the label must be true.
            sources = doc.get("research", {}).get("sources", [])
            if len(sources) < 6:
                err(f"{rel(d)}/book.json: complete status requires at least six useful sources")
            independent_reception = [s for s in sources if s.get("independence") == "independent"
                                     and s.get("type") in {"professional-review", "specialist-review"}]
            if len(independent_reception) < 2:
                err(f"{rel(d)}/book.json: complete status requires two independent reception sources")
            review = (content or {}).get("workflow", {}).get("quality_review", {})
            if review.get("status") != "passed" or not review.get("reviewed_at"):
                err(f"{rel(content_path)}: complete status requires a dated, passed quality review")
            incomplete_checks = [name for name, passed in review.get("checks", {}).items()
                                 if not passed]
            expected_checks = {
                "identity_and_metadata", "content_fidelity", "claim_support",
                "counterevidence", "citation_entailment", "product_fit",
                "plain_language", "audio_pronunciation",
            }
            missing_checks = expected_checks - set(review.get("checks", {}))
            if incomplete_checks or missing_checks:
                names = sorted(set(incomplete_checks) | missing_checks)
                err(f"{rel(content_path)}: quality review checks not passed: {', '.join(names)}")

        # scripts + audio
        row = {"book": doc, "durations": {}}
        for duration in durations:
            entry = {"script": None, "words": None, "audio": None}
            sp = d / "scripts" / f"{duration}.md"
            # The narration text, not the file: front matter carries the book id,
            # whose slug can contain a dictionary name the script never speaks.
            # Judging freshness on the file would strand such audio as
            # permanently stale, because regeneration reads the body alone.
            narration_text = ""
            if sp.exists():
                meta, body = parse_front_matter(sp)
                narration_text = spoken_text(body)
                entry["script"] = meta.get("status", "?")
                entry["words"] = word_count(body)
                if meta.get("book_id") != d.name:
                    err(f"{rel(sp)}: book_id front matter mismatch")
                if meta.get("duration") != duration:
                    err(f"{rel(sp)}: duration front matter does not match filename")
                if meta.get("source") != "content.json":
                    err(f"{rel(sp)}: source front matter must be 'content.json'")
                target = levels[duration]["target_words"]
                if meta.get("target_words") != target:
                    err(f"{rel(sp)}: target_words {meta.get('target_words')} != configured {target}")
                if meta.get("status") == "complete":
                    low, high = target * (1 - tolerance), target * (1 + tolerance)
                    if not (low <= entry["words"] <= high):
                        err(f"{rel(sp)}: {entry['words']} words is outside {target}±{tolerance:.0%}")
                    for pattern, problem in NARRATION_META_PATTERNS.items():
                        if re.search(pattern, body, flags=re.IGNORECASE):
                            err(f"{rel(sp)}: narration {problem}; keep research metadata out of audio")

            # audio + sidecar, one pair per voice: <level>.<voice>.<format> + .json
            audio_files = list((d / "audio").glob(f"{duration}.*")) if (d / "audio").exists() else []
            media = [a for a in audio_files if a.suffix != ".json"]
            sidecars = [a for a in audio_files if a.suffix == ".json"]
            script_sha = hashlib.sha256(sp.read_bytes()).hexdigest() if sp.exists() else None
            for audio_file in media:
                parts = audio_file.name.split(".")
                if len(parts) != 3:
                    err(f"{rel(audio_file)}: audio files must be named <level>.<voice>.<format>")
                    entry["audio"] = entry["audio"] or "fresh"
                    continue
                voice = parts[1]
                sidecar_path = d / "audio" / f"{duration}.{voice}.json"
                if not sidecar_path.exists():
                    reporter = err if audio_cfg["tts"].get("metadata_sidecar_required") else warn
                    reporter(f"{rel(audio_file)}: audio present without sidecar {sidecar_path.name}")
                    entry["audio"] = entry["audio"] or "fresh"
                    continue
                sidecar = load_json(sidecar_path)
                if sidecar is None:
                    continue
                validate_schema(sidecar, "audio-sidecar.schema.json", sidecar_path)
                if sidecar.get("voice") != voice:
                    err(f"{rel(sidecar_path)}: sidecar voice '{sidecar.get('voice')}' "
                        f"does not match filename voice '{voice}'")
                if sidecar.get("source_script_sha256") != script_sha:
                    warn(f"{rel(audio_file)}: audio is stale (script changed since generation)")
                    entry["audio"] = "stale"
                elif sidecar.get("pronunciation_dictionary_sha256") != pronunciation_sha \
                        and not pronunciation_is_current(
                            narration_text, sidecar, pronunciations_cfg["entries"]):
                    warn(f"{rel(audio_file)}: audio is stale (pronunciation dictionary changed "
                         "for a term this script uses)")
                    entry["audio"] = "stale"
                else:
                    entry["audio"] = entry["audio"] or "fresh"
            for orphan in sidecars:
                stem = orphan.name[: -len(".json")]
                if not any(m.name.startswith(stem + ".") for m in media):
                    warn(f"{rel(orphan)}: sidecar present but audio file missing")
            row["durations"][duration] = entry
        status_rows[d.name] = row

        if wf.get("status") == "complete":
            missing = [du for du, e in row["durations"].items()
                       if levels[du]["required"] and e["script"] != "complete"]
            if missing:
                err(f"{rel(d)}/book.json: status 'complete' but scripts not complete: {', '.join(missing)}")
            missing_audio = [
                du for du, entry in row["durations"].items()
                if levels[du]["required"] and entry["audio"] != "fresh"
            ]
            if missing_audio:
                err(
                    f"{rel(d)}/book.json: status 'complete' but local audio is missing or stale: "
                    f"{', '.join(missing_audio)}"
                )

    # --- playlists ---
    playlists_path = ROOT / "data/playlists.json"
    if playlists_path.exists():
        pl = load_json(playlists_path)
        if pl is not None:
            validate_schema(pl, "playlists.schema.json", playlists_path)
            playlist_ids = [p.get("id") for p in pl.get("playlists", [])]
            for duplicate in duplicates(playlist_ids):
                err(f"data/playlists.json: duplicate playlist id '{duplicate}'")
            for p in pl.get("playlists", []):
                for item in p.get("items", []):
                    if item["book_id"] not in entities:
                        err(f"data/playlists.json: playlist '{p.get('name')}' references unknown book "
                            f"'{item['book_id']}'")
                    elif entities[item["book_id"]]["kind"] != "book":
                        err(f"data/playlists.json: playlist '{p.get('name')}' item is not a book")
                    if item["duration"] not in audio_cfg["levels"]:
                        err(f"data/playlists.json: playlist '{p.get('name')}' has unknown duration "
                            f"'{item['duration']}'")
                book_ids = [item["book_id"] for item in p.get("items", [])]
                for duplicate in duplicates(book_ids):
                    warn(f"data/playlists.json: playlist '{p.get('name')}' lists '{duplicate}' "
                         "at more than one duration; playlists should hold one entry per book")

    # --- processing queue ---
    queue_path = ROOT / "data/queue.json"
    if queue_path.exists():
        qdoc = load_json(queue_path)
        if qdoc is not None:
            validate_schema(qdoc, "queue.schema.json", queue_path)
            queue_ids = [item["book_id"] for item in qdoc.get("queue", [])]
            for duplicate in duplicates(queue_ids):
                err(f"data/queue.json: '{duplicate}' is queued more than once")
            priorities = [item["priority"] for item in qdoc.get("queue", [])]
            for duplicate in duplicates(priorities):
                warn(f"data/queue.json: priority {duplicate} is used more than once; order is ambiguous")
            for item in qdoc.get("queue", []):
                if item["book_id"] not in entities or entities[item["book_id"]]["kind"] != "book":
                    err(f"data/queue.json: unknown book '{item['book_id']}'")
                    continue
                book_doc = load_json(ROOT / "library/books" / item["book_id"] / "book.json") \
                    if (ROOT / "library/books" / item["book_id"] / "book.json").exists() else None
                book_status = (book_doc or {}).get("workflow", {}).get("status")
                if item["status"] == "done" and book_status != "complete":
                    warn(f"data/queue.json: '{item['book_id']}' is marked done but book.json "
                         f"status is '{book_status}'")

    return report(quiet, status_rows, durations)


def report(quiet: bool, status_rows: dict, durations: list[str]) -> int:
    if not quiet and status_rows:
        print("Library status")
        print(f"  {'book':40} {'status':20} {'coverage':22} " + " ".join(f"{d:>12}" for d in durations))
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
