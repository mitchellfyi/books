"""check.py is the gate every book passes through; these hold its behaviour.

The end-to-end cases run against a throwaway one-book repository assembled
from the real schemas, config and templates, so they exercise the same code
path as `./bookflow check` without asserting anything about the live library.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check  # noqa: E402  (needs scripts/ on the path, as uv run gives it)

FIXTURE_BOOK = "deep-work-newport"


def build_repository(root: Path, book_id: str = FIXTURE_BOOK) -> Path:
    """Assemble a valid single-book repository from the real one.

    Audio media are stand-ins: check reads the committed sidecars for
    provenance and only looks for a matching file beside them, so the fixture
    does not depend on locally generated audio.
    """
    for folder in ("schemas", "config", "taxonomy"):
        shutil.copytree(ROOT / folder, root / folder)
    book_source = ROOT / "library/books" / book_id
    book_target = root / "library/books" / book_id
    shutil.copytree(book_source, book_target)

    book = json.loads((book_source / "book.json").read_text(encoding="utf-8"))
    author_ids = book["author_ids"]
    for author_id in author_ids:
        shutil.copytree(ROOT / "library/authors" / author_id,
                        root / "library/authors" / author_id)

    for sidecar in (book_target / "audio").glob("*.json"):
        level, voice, _ = sidecar.name.split(".")
        media = json.loads(sidecar.read_text(encoding="utf-8"))["output_format"]
        (book_target / "audio" / f"{level}.{voice}.{media}").touch()

    catalog = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    keep = {book_id, *author_ids}
    catalog["entities"] = [e for e in catalog["entities"] if e["id"] in keep]
    write(root / "data/catalog.json", catalog)

    relationships = json.loads((ROOT / "data/relationships.json").read_text(encoding="utf-8"))
    relationships["relationships"] = [
        r for r in relationships["relationships"]
        if {r["source_id"], r["target_id"]} <= keep
    ]
    write(root / "data/relationships.json", relationships)
    write(root / "data/queue.json", {
        "$schema": "../schemas/queue.schema.json", "schema_version": 1,
        "queue": [{"book_id": book_id, "priority": 1, "status": "done",
                   "source": "user", "added_at": "2026-01-01"}],
    })
    return root


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@contextlib.contextmanager
def repository_at(root: Path):
    """Run check against a throwaway repository, with its module state reset."""
    original = check.ROOT
    check.ROOT = root
    check.errors.clear()
    check.warnings.clear()
    check.schema_validator.cache_clear()
    check.load_json_once.cache_clear()
    try:
        yield
    finally:
        check.ROOT = original
        check.errors.clear()
        check.warnings.clear()
        check.schema_validator.cache_clear()
        check.load_json_once.cache_clear()


class HelperTests(unittest.TestCase):
    def test_duplicates_reports_each_repeat_once_in_document_order(self) -> None:
        self.assertEqual(check.duplicates(["b", "a", "b", "c", "a", "b"]), ["b", "a"])

    def test_duplicates_of_unique_values_is_empty(self) -> None:
        self.assertEqual(check.duplicates(["a", "b"]), [])
        self.assertEqual(check.duplicates([]), [])

    def test_library_dirs_of_a_missing_folder_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with repository_at(Path(directory)):
                self.assertEqual(check.library_dirs("library/books"), [])

    def test_library_dirs_ignores_loose_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "library/books/one").mkdir(parents=True)
            (root / "library/books/.DS_Store").write_text("", encoding="utf-8")
            with repository_at(root):
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


class SourceIdTests(unittest.TestCase):
    def collect(self, doc: dict, **options) -> list[str]:
        with repository_at(ROOT):
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
        with repository_at(root):
            with contextlib.redirect_stdout(io.StringIO()):
                status = check.main(["--quiet"])
            return status, list(check.errors), list(check.warnings)

    def test_a_complete_book_passes_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, errors, warnings = self.run_check(build_repository(Path(directory)))
        self.assertEqual((status, errors, warnings), (0, [], []))

    def test_a_word_count_outside_tolerance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            script.write_text(script.read_text(encoding="utf-8") + "\n\nAnd more. " * 40,
                              encoding="utf-8")
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("words is outside" in e for e in errors), errors)

    def test_narration_naming_the_product_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            meta, _, body = script.read_text(encoding="utf-8").partition("\n---\n")
            script.write_text(f"{meta}\n---\nThis summary explains the book.{body}",
                              encoding="utf-8")
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("announces the summary" in e for e in errors), errors)

    def test_a_content_source_missing_from_book_json_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            content["ideas"][0]["source_ids"] = ["not-a-real-source"]
            write(path, content)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("cites unknown source 'not-a-real-source'" in e for e in errors), errors)

    def test_a_stale_stored_rating_total_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "content.json"
            content = read(path)
            content["assessment"]["rating"]["score"] = 1.0
            write(path, content)
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("does not equal calculated" in e for e in errors), errors)

    def test_an_uncatalogued_book_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            (root / "library/books/ghost-book").mkdir()
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("has no catalog entry" in e for e in errors), errors)

    def test_a_changed_script_stales_its_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            script.write_text(script.read_text(encoding="utf-8").replace("the", "The", 1),
                              encoding="utf-8")
            status, errors, warnings = self.run_check(root)
        self.assertTrue(any("script changed since generation" in w for w in warnings), warnings)
        # A complete book with stale audio is an error, not only a warning.
        self.assertEqual(status, 1)
        self.assertTrue(any("local audio is missing or stale" in e for e in errors), errors)

    def test_a_missing_sidecar_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            audio = root / "library/books" / FIXTURE_BOOK / "audio"
            next(audio.glob("30-seconds.*.json")).unlink()
            status, errors, _ = self.run_check(root)
        self.assertEqual(status, 1)
        self.assertTrue(any("audio present without sidecar" in e for e in errors), errors)

    def test_a_playlist_naming_an_unknown_book_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
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
            root = build_repository(Path(directory))
            (root / "library/books" / FIXTURE_BOOK / "content.json").write_text(
                "{not json", encoding="utf-8")
            with repository_at(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = check.main(["--quiet", "no-such-book"])
                errors = list(check.errors)
        self.assertEqual(status, 1)
        self.assertEqual(errors, ["no such book: no-such-book"])


if __name__ == "__main__":
    unittest.main()
