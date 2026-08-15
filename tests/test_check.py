"""check.py is the gate every book passes through; these hold its behaviour.

The end-to-end cases run against a throwaway one-book repository assembled
from the real schemas, config and templates, so they exercise the same code
path as `./bookflow check` without asserting anything about the live library.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check
from fixtures import FIXTURE_BOOK, ROOT, check_at, one_book_repository, read, write


class HelperTests(unittest.TestCase):
    def test_duplicates_reports_each_repeat_once_in_document_order(self) -> None:
        self.assertEqual(check.duplicates(["b", "a", "b", "c", "a", "b"]), ["b", "a"])

    def test_duplicates_of_unique_values_is_empty(self) -> None:
        self.assertEqual(check.duplicates(["a", "b"]), [])
        self.assertEqual(check.duplicates([]), [])

    def test_library_dirs_of_a_missing_folder_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with check_at(Path(directory)):
                self.assertEqual(check.library_dirs("library/books"), [])

    def test_library_dirs_ignores_loose_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "library/books/one").mkdir(parents=True)
            (root / "library/books/.DS_Store").write_text("", encoding="utf-8")
            with check_at(root):
                self.assertEqual([d.name for d in check.library_dirs("library/books")], ["one"])


class PointerTests(unittest.TestCase):
    doc = {"a": {"b": [{"c": 1}]}, "x/y": 2, "x~y": 3}

    def test_walks_objects_and_array_indices(self) -> None:
        self.assertTrue(check.resolve_pointer(self.doc, "/a/b/0/c"))

    def test_unknown_key_or_index_does_not_resolve(self) -> None:
        self.assertFalse(check.resolve_pointer(self.doc, "/a/missing"))
        self.assertFalse(check.resolve_pointer(self.doc, "/a/b/1"))
        self.assertFalse(check.resolve_pointer(self.doc, "/a/b/0/c/deeper"))

    def test_escaped_tokens_resolve(self) -> None:
        self.assertTrue(check.resolve_pointer(self.doc, "/x~1y"))
        self.assertTrue(check.resolve_pointer(self.doc, "/x~0y"))


class InlineSourceTests(unittest.TestCase):
    def test_an_object_carrying_source_ids_is_inline(self) -> None:
        self.assertTrue(check.has_inline_sources({"a": {"source_ids": ["s1"]}}, "/a"))

    def test_a_list_counts_only_when_every_item_carries_them(self) -> None:
        doc = {"a": [{"source_ids": []}, {"source_ids": ["s1"]}], "b": [{"source_ids": []}, {}]}
        self.assertTrue(check.has_inline_sources(doc, "/a"))
        self.assertFalse(check.has_inline_sources(doc, "/b"))

    def test_an_empty_list_is_not_inline(self) -> None:
        self.assertFalse(check.has_inline_sources({"a": []}, "/a"))

    def test_a_pointer_through_a_list_index_resolves(self) -> None:
        # Citations name one item, not the whole list: '/selected_works/0'.
        doc = {"a": [{"source_ids": ["s1"]}, {"other": 1}]}
        self.assertTrue(check.has_inline_sources(doc, "/a/0"))
        self.assertFalse(check.has_inline_sources(doc, "/a/1"))
        self.assertFalse(check.has_inline_sources(doc, "/a/9"))


class SourceIdTests(unittest.TestCase):
    def collect(self, doc: dict, **options) -> list[str]:
        with check_at(ROOT):
            check.check_source_ids(doc, ROOT / "book.json", {"s1"}, **options)
            return list(check.errors)

    def test_an_unknown_source_is_reported_with_its_location(self) -> None:
        problems = self.collect({"ideas": [{"source_ids": ["s9"]}]}, require_sources=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("/ideas/0 cites unknown source 's9'", problems[0])

    def test_an_empty_list_is_reported_only_when_sources_are_required(self) -> None:
        doc = {"card": {"source_ids": []}}
        self.assertIn("has no supporting sources", self.collect(doc, require_sources=True)[0])
        self.assertEqual(self.collect(doc, require_sources=False), [])

    def test_the_skipped_branch_is_left_alone_at_every_depth(self) -> None:
        doc = {"research": {"sources": [{"source_ids": ["s9"]}]},
               "ideas": [{"research": {"source_ids": ["s9"]}}]}
        self.assertEqual(self.collect(doc, require_sources=True, skip="research"), [])


class LibraryCheckTests(unittest.TestCase):
    """End to end over a throwaway repository built from the real one."""

    def run_check(self, root: Path) -> tuple[int, list[str], list[str]]:
        with check_at(root):
            with contextlib.redirect_stdout(io.StringIO()):
                status = check.main(["--quiet"])
            return status, list(check.errors), list(check.warnings)

    def test_a_complete_book_passes_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, errors, warnings = self.run_check(one_book_repository(Path(directory)))
        self.assertEqual((status, errors, warnings), (0, [], []))

    def test_a_word_count_outside_tolerance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            script.write_text(script.read_text(encoding="utf-8") + "\n\nAnd more. " * 40,
                              encoding="utf-8")
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("words is outside" in e for e in errors), errors)

    def test_narration_naming_the_product_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            meta, _, body = script.read_text(encoding="utf-8").partition("\n---\n")
            script.write_text(f"{meta}\n---\nThis summary explains the book.{body}",
                              encoding="utf-8")
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("announces the summary" in e for e in errors), errors)

    def test_a_content_source_missing_from_book_json_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            content["ideas"][0]["source_ids"] = ["not-a-real-source"]
            write(path, content)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("cites unknown source 'not-a-real-source'" in e for e in errors), errors)

    def test_a_stale_stored_rating_total_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            content["assessment"]["rating"]["score"] = 1.0
            write(path, content)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("does not equal calculated" in e for e in errors), errors)

    def test_an_uncatalogued_book_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            (root / "library/books/ghost-book").mkdir()
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("has no catalog entry" in e for e in errors), errors)

    def test_a_changed_script_stales_its_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            script.write_text(script.read_text(encoding="utf-8").replace("the", "The", 1),
                              encoding="utf-8")
            status, errors, warnings = self.run_check(root)
        self.assertTrue(any("script changed since generation" in w for w in warnings), warnings)
        # A complete book with stale audio is an error, not only a warning.
        self.assertEqual(status, 1)
        self.assertTrue(any("local audio is stale" in e for e in errors), errors)

    def test_audio_that_was_never_generated_here_is_not_an_error(self) -> None:
        # Recordings are deliberately not committed, so a fresh clone has none.
        # Reporting that as an error on every book would make check untrusted.
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            for media in (root / "library/books" / FIXTURE_BOOK / "audio").glob("*.mp3"):
                media.unlink()
            status, errors, warnings = self.run_check(root)
        self.assertEqual((status, errors), (0, []))
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("no local audio for", warnings[0])
        self.assertIn(f"./bookflow audio {FIXTURE_BOOK}", warnings[0])

    def test_a_missing_sidecar_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            audio = root / "library/books" / FIXTURE_BOOK / "audio"
            next(audio.glob("30-seconds.*.json")).unlink()
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("audio present without sidecar" in e for e in errors), errors)

    def test_a_default_naming_something_the_config_does_not_offer_fails(self) -> None:
        # Both fail silently at runtime: the player takes its first speed, the
        # generator takes whatever voice it can find.
        for change, expected in (
            ({"default_playback_speed": 1.15}, "default_playback_speed"),
            ({"tts": {"default_voice": "bf_nobody"}}, "default_voice"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = one_book_repository(Path(directory))
                config = read(root / "config/audio.json")
                for key, value in change.items():
                    config[key] = {**config[key], **value} if isinstance(value, dict) else value
                write(root / "config/audio.json", config)
                status, errors, _ = self.run_check(root)
                self.assertEqual(status, 1)
                self.assertTrue(any(expected in e for e in errors), errors)

    def edge(self, root: Path, **fields) -> None:
        path = root / "data/relationships.json"
        document = read(path)
        document["relationships"].append({
            "id": "probe", "type": "related-to", "basis": "inference",
            "description": "A probe edge.", "source_refs": [], "confidence": "high",
            **fields,
        })
        write(path, document)

    def test_a_schema_pointer_at_the_wrong_depth_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            content["$schema"] = "../../schemas/content.schema.json"
            write(path, content)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("does not resolve to schemas/content.schema.json" in e
                            for e in errors), errors)

    def test_an_absolute_schema_pointer_is_left_alone(self) -> None:
        # A URI is a legitimate way to write $schema; only relative pointers
        # can silently break by moving depth, so only those are resolved.
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            content["$schema"] = "https://example.org/content.schema.json"
            write(path, content)
            status, errors, warnings = self.run_check(root)
        self.assertEqual((status, errors, warnings), (0, [], []))

    def test_a_spelling_claimed_twice_names_both_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "config/pronunciations.json"
            document = read(path)
            owner = document["entries"][0]["term"]
            document["entries"].append({**document["entries"][1], "term": owner})
            write(path, document)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any(f"is already claimed by entry '{owner}'" in e for e in errors), errors)

    def test_an_edge_that_links_a_book_to_itself_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            self.edge(root, source_id=FIXTURE_BOOK, target_id=FIXTURE_BOOK)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any(f"'probe' links '{FIXTURE_BOOK}' to itself" in e for e in errors), errors)

    def test_an_unknown_entity_at_both_ends_is_reported_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            self.edge(root, source_id="nowhere", target_id="nowhere")
            _, errors, _ = self.run_check(root)
        self.assertEqual([e for e in errors if "unknown entity 'nowhere'" in e],
                         ["data/relationships.json: 'probe' references unknown entity 'nowhere'"])

    def test_each_book_map_part_names_itself_when_it_cites_a_lost_idea(self) -> None:
        # Renaming one idea usually breaks several parts at once; identical
        # lines would leave nothing to search for.
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            for section in content["book_map"][:2]:
                section["idea_ids"] = ["renamed-away"]
            write(path, content)
            status, errors, _ = self.run_check(root)
        cited = [e for e in errors if "cites unknown idea 'renamed-away'" in e]
        self.assertEqual(status, 1)
        self.assertEqual(len(cited), 2, errors)
        self.assertEqual(len(set(cited)), 2, cited)

    def test_a_thin_source_list_blocks_a_complete_book(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "book.json"
            book = read(path)
            kept = book["research"]["sources"][:1]
            book["research"]["sources"] = kept
            write(path, book)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any(f"at least {check.MINIMUM_BOOK_SOURCES} useful sources" in e
                            for e in errors), errors)
        self.assertTrue(any(f"{check.MINIMUM_RECEPTION_SOURCES} independent reception" in e
                            for e in errors), errors)

    def test_files_left_by_a_renamed_level_are_reported(self) -> None:
        # This library renamed a level once. Every other check iterates the
        # configured levels, so what the rename left behind is invisible.
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            book = root / "library/books" / FIXTURE_BOOK
            (book / "scripts/6-minutes.md").write_text("old", encoding="utf-8")
            (book / "audio/6-minutes.bf_emma.json").write_text("{}", encoding="utf-8")
            status, errors, warnings = self.run_check(root)
        self.assertEqual((status, errors), (0, []))
        self.assertEqual(len(warnings), 2, warnings)
        self.assertTrue(all("not a level in config/audio.json" in w for w in warnings), warnings)

    def test_a_playlist_naming_an_unknown_book_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            write(root / "data/playlists.json", {
                "$schema": "../schemas/playlists.schema.json", "schema_version": 1,
                "playlists": [{"id": "p", "name": "P", "updated_at": "2026-01-01T00:00:00Z",
                               "items": [{"book_id": "ghost", "duration": "30-seconds"}]}],
            })
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("references unknown book 'ghost'" in e for e in errors), errors)

    def test_naming_a_book_limits_the_book_level_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            (root / "library/books" / FIXTURE_BOOK / "content.json").write_text(
                "{not json", encoding="utf-8")
            with check_at(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = check.main(["--quiet", "no-such-book"])
                errors = list(check.errors)
        self.assertEqual(status, 1)
        self.assertEqual(errors, ["no such book: no-such-book"])


class BrokenInputTests(unittest.TestCase):
    """check runs when files are half-written; that is when it is most needed.

    Each case leaves the repository in a state an interrupted edit produces and
    asserts check reports it and keeps going, rather than ending in a traceback
    that hides everything else.
    """

    def run_check(self, root: Path, argv: list[str] | None = None) -> tuple[int, list, list, str]:
        with check_at(root):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                status = check.main(argv if argv is not None else ["--quiet"])
            return status, list(check.errors), list(check.warnings), output.getvalue()

    def broken(self, relative: str) -> tuple[int, list, list, str]:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            (root / relative).write_text("{not json", encoding="utf-8")
            return self.run_check(root)

    def test_an_unparseable_author_profile_is_named_once_and_survived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            profile = next((root / "library/authors").glob("*/author.json"))
            profile.write_text("{not json", encoding="utf-8")
            status, errors, _, _ = self.run_check(root)
        named = [e for e in errors if "invalid JSON" in e]
        self.assertEqual(status, 1)
        self.assertEqual(len(named), 1, errors)
        self.assertIn(f"library/authors/{profile.parent.name}/author.json", named[0])

    def test_an_unparseable_sidecar_is_named_and_survived(self) -> None:
        status, errors, _, _ = self.broken(
            f"library/books/{FIXTURE_BOOK}/audio/30-seconds.bf_emma.json")
        self.assertEqual(status, 1)
        self.assertTrue(any("30-seconds.bf_emma.json: invalid JSON" in e for e in errors), errors)

    def test_unparseable_playlists_and_queue_are_named_and_survived(self) -> None:
        for relative in ("data/playlists.json", "data/queue.json"):
            with self.subTest(relative):
                status, errors, _, _ = self.broken(relative)
                self.assertEqual(status, 1)
                self.assertTrue(any(f"{relative}: invalid JSON" in e for e in errors), errors)

    def test_a_missing_queue_or_playlists_file_is_not_a_problem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            (root / "data/queue.json").unlink()
            status, errors, warnings, _ = self.run_check(root)
        self.assertEqual((status, errors, warnings), (0, [], []))

    def test_a_level_with_no_script_is_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            (root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md").unlink()
            status, errors, _, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("scripts not complete: 30-seconds" in e for e in errors), errors)

    def test_a_source_ref_to_an_unparseable_file_is_not_called_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            edit_relationships(root, lambda d: d["relationships"][0].__setitem__(
                "source_refs", ["data/broken.json#anything"]))
            (root / "data/broken.json").write_text("{not json", encoding="utf-8")
            status, errors, _, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("data/broken.json: invalid JSON" in e for e in errors), errors)
        self.assertFalse(any("source_ref file missing" in e for e in errors), errors)

    def test_a_missing_shared_file_stops_before_the_consequences(self) -> None:
        # Every later check reads one of these; carrying on would bury the one
        # real problem under a page of errors caused by it.
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            (root / "taxonomy/tags.json").unlink()
            status, errors, _, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertEqual(errors, ["taxonomy/tags.json: file missing"])

    def test_the_status_table_is_printed_unless_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            _, _, _, loud = self.run_check(root, [])
            _, _, _, quiet = self.run_check(root, ["--quiet"])
        self.assertIn("Library status", loud)
        self.assertIn(FIXTURE_BOOK, loud)
        self.assertIn("script+audio", loud)
        self.assertNotIn("Library status", quiet)


def book_file(root: Path, name: str) -> Path:
    return root / "library/books" / FIXTURE_BOOK / name


def edit(root: Path, name: str, mutate) -> None:
    path = book_file(root, name)
    document = read(path)
    mutate(document)
    write(path, document)


def edit_script(root: Path, level: str, old: str, new: str) -> None:
    path = book_file(root, f"scripts/{level}.md")
    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def edit_config(root: Path, name: str, mutate) -> None:
    path = root / "config" / name
    document = read(path)
    mutate(document)
    write(path, document)


def edit_relationships(root: Path, mutate) -> None:
    path = root / "data/relationships.json"
    document = read(path)
    mutate(document)
    write(path, document)


class DefectTests(unittest.TestCase):
    """One row per rule check enforces on top of the schemas.

    Mutation testing found sixteen of these branches could be deleted without
    a test noticing. Each row breaks one thing in an otherwise valid
    repository and names the message that must come back.
    """

    CASES = [
        ("content book_id",
         lambda r: edit(r, "content.json", lambda c: c.__setitem__("book_id", "elsewhere")),
         "book_id does not match directory name"),
        ("fiction",
         lambda r: edit(r, "content.json", lambda c: c.__setitem__("content_type", "fiction")),
         "accepts non-fiction only"),
        ("book_map order",
         lambda r: edit(r, "content.json",
                        lambda c: c["book_map"][0].__setitem__("order", 9)),
         "book_map order must be consecutive from 1"),
        ("book id",
         lambda r: edit(r, "book.json", lambda b: b.__setitem__("id", "elsewhere")),
         "does not match directory name"),
        ("author id",
         lambda r: (lambda p: write(p, {**read(p), "id": "someone-else"}))(
             next((r / "library/authors").glob("*/author.json"))),
         "author.json: id 'someone-else' does not match directory name"),
        ("unknown tag",
         lambda r: edit(r, "book.json",
                        lambda b: b["discovery"]["tag_ids"].append("not-a-tag")),
         "'not-a-tag' is not in taxonomy/tags.json"),
        ("unknown author",
         lambda r: edit(r, "book.json", lambda b: b["author_ids"].append("nobody")),
         "unknown author id 'nobody'"),
        ("citation pointer",
         lambda r: edit(r, "book.json",
                        lambda b: b["research"].setdefault("citations", {}).__setitem__(
                            "/no/such/field", [b["research"]["sources"][0]["id"]])),
         "citation pointer '/no/such/field' does not resolve"),
        ("sidecar voice",
         lambda r: edit(r, "audio/30-seconds.bf_emma.json",
                        lambda s: s.__setitem__("voice", "bm_george")),
         "does not match filename voice 'bf_emma'"),
        ("audio filename",
         lambda r: book_file(r, "audio/30-seconds.mp3").write_bytes(b""),
         "must be named <level>.<voice>.<format>"),
        ("script target_words",
         lambda r: edit_script(r, "30-seconds", "target_words: 75", "target_words: 80"),
         "target_words 80 != configured 75"),
        ("script duration",
         lambda r: edit_script(r, "30-seconds", "duration: 30-seconds", "duration: 5-minutes"),
         "duration front matter does not match filename"),
        ("script source",
         lambda r: edit_script(r, "30-seconds", "source: content.json", "source: elsewhere"),
         "source front matter must be 'content.json'"),
        ("playlist duration",
         lambda r: write(r / "data/playlists.json", {
             "$schema": "../schemas/playlists.schema.json", "schema_version": 1,
             "playlists": [{"id": "p", "name": "P", "updated_at": "2026-01-01T00:00:00Z",
                            "items": [{"book_id": FIXTURE_BOOK, "duration": "99-hours"}]}]}),
         "has unknown duration '99-hours'"),
        ("catalogued path",
         lambda r: write(r / "data/catalog.json", {
             **read(r / "data/catalog.json"),
             "entities": [{**e, "path": "library/books/gone/book.json"}
                          for e in read(r / "data/catalog.json")["entities"]]}),
         "does not exist: library/books/gone/book.json"),
        ("rubric weights",
         lambda r: edit_config(r, "rating.json",
                               lambda c: c["dimensions"][0].__setitem__("weight", 0.9)),
         "dimension weights total"),
        ("alias longer than term",
         lambda r: edit_config(r, "pronunciations.json",
                               lambda c: c["entries"][0]["aliases"].append(
                                   "Doctor " + c["entries"][0]["term"])),
         "has more words than term"),
        ("script book_id",
         lambda r: edit_script(r, "30-seconds", f"book_id: {FIXTURE_BOOK}",
                               "book_id: elsewhere"),
         "book_id front matter mismatch"),
        ("researched without content",
         lambda r: book_file(r, "content.json").unlink(),
         "researched books require structured content"),
        ("workflow status disagreement",
         lambda r: edit(r, "content.json",
                        lambda c: c["workflow"].__setitem__("status", "researched-partial")),
         "workflow status differs from book.json"),
        ("quality review undated",
         lambda r: edit(r, "content.json",
                        lambda c: c["workflow"]["quality_review"].__setitem__("reviewed_at", "")),
         "requires a dated, passed quality review"),
        ("quality review incomplete",
         lambda r: edit(r, "content.json",
                        lambda c: c["workflow"]["quality_review"]["checks"].pop("counterevidence")),
         "quality review checks not passed: counterevidence"),
        ("complete with a draft script",
         lambda r: edit_script(r, "30-seconds", "status: complete", "status: draft"),
         "scripts not complete: 30-seconds"),
        ("citation map unknown source",
         lambda r: edit(r, "book.json",
                        lambda b: b["research"].setdefault("citations", {}).__setitem__(
                            "/title", ["no-such-source"])),
         "citations['/title'] cites unknown source 'no-such-source'"),
        ("dictionary path",
         lambda r: edit_config(r, "audio.json",
                               lambda c: c["tts"].__setitem__(
                                   "pronunciation_dictionary", "config/elsewhere.json")),
         "pronunciation_dictionary must point to config/pronunciations.json"),
        ("tag alias collides",
         lambda r: (lambda p: write(p, {**read(p), "tags": [
             {**read(p)["tags"][0], "aliases": [read(p)["tags"][1]["id"]]},
             *read(p)["tags"][1:]]}))(r / "taxonomy/tags.json"),
         "collides with a canonical tag id"),
        ("catalogued without path",
         lambda r: write(r / "data/catalog.json", {
             **read(r / "data/catalog.json"),
             "entities": [{k: v for k, v in e.items() if k != "path"}
                          for e in read(r / "data/catalog.json")["entities"]]}),
         "has no path"),
        ("directory kind",
         lambda r: write(r / "data/catalog.json", {
             **read(r / "data/catalog.json"),
             "entities": [{**e, "kind": "author" if e["kind"] == "book" else "book"}
                          for e in read(r / "data/catalog.json")["entities"]]}),
         "catalog entry kind mismatch"),
        ("source_ref file missing",
         lambda r: edit_relationships(r, lambda d: d["relationships"][0].__setitem__(
             "source_refs", ["library/books/gone/book.json#anything"])),
         "source_ref file missing: library/books/gone/book.json"),
        ("source_ref fragment missing",
         lambda r: edit_relationships(r, lambda d: d["relationships"][0].__setitem__(
             "source_refs", [f"library/books/{FIXTURE_BOOK}/book.json#no-such-source"])),
         "source_ref '#no-such-source' not found"),
        ("playlist item is an author",
         lambda r: write(r / "data/playlists.json", {
             "$schema": "../schemas/playlists.schema.json", "schema_version": 1,
             "playlists": [{"id": "p", "name": "P", "updated_at": "2026-01-01T00:00:00Z",
                            "items": [{"book_id": read(book_file(r, "book.json"))["author_ids"][0],
                                       "duration": "30-seconds"}]}]}),
         "item is not a book"),
        ("queue names an unknown book",
         lambda r: (lambda p: write(p, {**read(p), "queue": [
             {**read(p)["queue"][0], "book_id": "no-such-book"}]}))(r / "data/queue.json"),
         "unknown book 'no-such-book'"),
    ]

    # Rules that report a warning: real but not disqualifying.
    WARNING_CASES = [
        ("explicit without refs",
         lambda r: edit_relationships(r, lambda d: d["relationships"][0].update(
             {"basis": "explicit", "source_refs": []})),
         "is explicit but has no source_refs"),
        # An author profile cites interpretive fields inline; adding a citation
        # map entry for one of them records the same thing twice.
        ("citation map duplicates inline",
         lambda r: (lambda p: write(p, {**(d := read(p)), "research": {
             **d["research"], "citations": {
                 **d["research"].get("citations", {}),
                 "/profile/biography": d["profile"]["biography"]["source_ids"]}}}))(
                     next((r / "library/authors").glob("*/author.json"))),
         "duplicates inline source_ids"),
        ("queue done but book unfinished",
         lambda r: edit(r, "book.json",
                        lambda b: b["workflow"].__setitem__("status", "researched-partial")),
         "is marked done but book.json status is 'researched-partial'"),
        ("thin author sources",
         lambda r: (lambda p: write(p, {**read(p), "research": {
             **read(p)["research"], "sources": read(p)["research"]["sources"][:1]}}))(
                 next((r / "library/authors").glob("*/author.json"))),
         "useful author sources"),
    ]

    def test_each_rule_reports_its_own_defect(self) -> None:
        for name, break_it, expected in self.CASES:
            with self.subTest(name):
                found, status = self.provoke(break_it)
                self.assertEqual(status, 1, found[0])
                self.assertTrue(any(expected in problem for problem in found[0]),
                                f"{name}: expected {expected!r} in {found[0]}")

    def test_each_warning_reports_its_own_concern(self) -> None:
        for name, break_it, expected in self.WARNING_CASES:
            with self.subTest(name):
                found, _ = self.provoke(break_it)
                self.assertTrue(any(expected in problem for problem in found[1]),
                                f"{name}: expected {expected!r} in {found[1]}")

    def provoke(self, break_it) -> tuple[tuple[list[str], list[str]], int]:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            break_it(root)
            with check_at(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = check.main(["--quiet"])
                return (list(check.errors), list(check.warnings)), status


if __name__ == "__main__":
    unittest.main()
