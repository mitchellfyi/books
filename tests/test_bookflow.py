from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import bookflow, bookflow_at, copy_into, empty_repository


class SlugTests(unittest.TestCase):
    def test_transliterates_and_kebabs(self) -> None:
        self.assertEqual(bookflow.slug("Ünicode Bôok"), "unicode-book")
        self.assertEqual(bookflow.slug("Thinking, Fast and Slow"), "thinking-fast-and-slow")

    def test_strips_leading_and_trailing_separators(self) -> None:
        self.assertEqual(bookflow.slug("  Hello!  "), "hello")

    def test_untransliterable_text_slugs_to_nothing(self) -> None:
        # Why init must check the derived id: this is what makes '-surname'.
        self.assertEqual(bookflow.slug("李白"), "")

    def test_is_idempotent(self) -> None:
        for text in ("Deep Work", "李白: Poems", "a--b", "-x-"):
            once = bookflow.slug(text)
            self.assertEqual(bookflow.slug(once), once, text)


class ScaffoldScriptsTests(unittest.TestCase):
    def scaffold(self, directory: str, book_id: str = "some-book") -> Path:
        book_dir = Path(directory) / book_id
        (book_dir / "scripts").mkdir(parents=True)
        bookflow.scaffold_scripts(book_dir, book_id)
        return book_dir

    def test_writes_one_script_per_configured_level(self) -> None:
        levels = bookflow.load_config("audio.json")["levels"]
        with tempfile.TemporaryDirectory() as directory:
            book_dir = self.scaffold(directory)
            written = sorted(p.stem for p in (book_dir / "scripts").glob("*.md"))
        self.assertEqual(written, sorted(levels))

    def test_front_matter_matches_the_configured_target(self) -> None:
        levels = bookflow.load_config("audio.json")["levels"]
        with tempfile.TemporaryDirectory() as directory:
            book_dir = self.scaffold(directory, "deep-work-newport")
            for level, settings in levels.items():
                meta, body = bookflow.parse_front_matter(book_dir / "scripts" / f"{level}.md")
                self.assertEqual(meta["book_id"], "deep-work-newport", level)
                self.assertEqual(meta["duration"], level)
                self.assertEqual(meta["target_words"], settings["target_words"])
                self.assertEqual(meta["source"], "content.json")
                self.assertEqual(meta["status"], "stub")
                self.assertTrue(body.strip(), level)

    def test_replaces_stale_scripts_and_leaves_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory) / "some-book"
            (book_dir / "scripts").mkdir(parents=True)
            (book_dir / "scripts" / "99-minutes.md").write_text("gone", encoding="utf-8")
            keep = book_dir / "scripts" / "keep.txt"
            keep.write_text("kept", encoding="utf-8")
            bookflow.scaffold_scripts(book_dir, "some-book")
            self.assertFalse((book_dir / "scripts" / "99-minutes.md").exists())
            self.assertEqual(keep.read_text(encoding="utf-8"), "kept")


class InitBookTests(unittest.TestCase):
    """init_book end to end against a throwaway copy of the repository.

    scaffold_scripts must run after replace_tree: reversing them expands a
    'book-id' substring inside the real id a second time, which scaffolds a
    book that fails check. Only a full init reaches that ordering.
    """

    def init(self, root: Path, title: str, author: str) -> Path:
        self.report = self.init_reporting(root, title, author)
        return root / "library/books"

    def init_reporting(self, root: Path, title: str, author: str) -> str:
        if not (root / "library/books").exists():
            empty_repository(root)
        with bookflow_at(root):
            # init_book prints a research prompt; keep it out of the test run.
            with contextlib.redirect_stdout(io.StringIO()) as output:
                bookflow.init_book(argparse.Namespace(
                    title=title, author=author, book_id=None, author_id=None,
                    force=True, note="", discovered=False))
        return output.getvalue()

    def test_joining_an_existing_author_profile_is_announced(self) -> None:
        # Ids come from the name, so two different people can collide on one.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.init_reporting(root, "One Book", "Jane Smith")
            second = self.init_reporting(root, "Another Book", "Jane Smith")
        self.assertIn("(new)", first)
        self.assertIn("(existing", second)
        self.assertIn("check it is the same person", second)

    def test_catalogue_aliases_survive_a_re_initialised_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_reporting(root, "One Book", "Jane Smith")
            catalog = json.loads((root / "data/catalog.json").read_text(encoding="utf-8"))
            for entity in catalog["entities"]:
                entity["aliases"] = ["a researched alias"]
            (root / "data/catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            shutil.rmtree(root / "library/books/one-book-smith")
            self.init_reporting(root, "One Book", "Jane Smith")
            catalog = json.loads((root / "data/catalog.json").read_text(encoding="utf-8"))
        self.assertEqual([e["aliases"] for e in catalog["entities"]],
                         [["a researched alias"], ["a researched alias"]])

    def test_an_id_containing_the_placeholder_is_not_expanded_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            books = self.init(Path(directory), "The Book ID Problem", "Jane Smith")
            book_dir = books / "the-book-id-problem-smith"
            self.assertTrue(book_dir.is_dir(), sorted(p.name for p in books.iterdir()))
            meta, _ = bookflow.parse_front_matter(book_dir / "scripts" / "30-seconds.md")
            self.assertEqual(meta["book_id"], "the-book-id-problem-smith")
            content = json.loads((book_dir / "content.json").read_text(encoding="utf-8"))
            self.assertEqual(content["book_id"], "the-book-id-problem-smith")

    def test_scaffolds_one_script_per_configured_level(self) -> None:
        levels = sorted(bookflow.load_config("audio.json")["levels"])
        with tempfile.TemporaryDirectory() as directory:
            books = self.init(Path(directory), "An Ordinary Book", "Alice Author")
            scripts = books / "an-ordinary-book-author" / "scripts"
            self.assertEqual(sorted(p.stem for p in scripts.glob("*.md")), levels)


class LoadTests(unittest.TestCase):
    def test_invalid_json_names_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                bookflow.load(path)
        self.assertIn("broken.json", str(caught.exception))
        self.assertIn("invalid JSON", str(caught.exception))

    def test_valid_json_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fine.json"
            path.write_text(json.dumps({"a": 1}), encoding="utf-8")
            self.assertEqual(bookflow.load(path), {"a": 1})

    def test_an_unreadable_file_names_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit) as missing:
                bookflow.load(Path(directory) / "absent.json")
            with self.assertRaises(SystemExit) as unreadable:
                bookflow.load(Path(directory))
        self.assertIn("absent.json: file missing", str(missing.exception))
        self.assertIn("cannot read", str(unreadable.exception))

    def test_read_json_reports_unreadable_files_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertIsNone(bookflow.read_json(broken))
            self.assertIsNone(bookflow.read_json(Path(directory) / "absent.json"))


class BookNeedsTests(unittest.TestCase):
    """book_needs summarises one book; a broken file must not end the report."""

    def needs(self, root: Path, book_id: str, files: dict[str, str]) -> str:
        copy_into(root, "config")
        directory = root / "library/books" / book_id
        directory.mkdir(parents=True)
        for name, text in files.items():
            (directory / name).write_text(text, encoding="utf-8")
        with bookflow_at(root):
            return bookflow.book_needs(book_id)

    def test_a_missing_scaffold_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_into(root, "config")
            with bookflow_at(root):
                self.assertEqual(bookflow.book_needs("ghost"), "scaffold missing")

    def test_unparseable_content_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                self.needs(Path(directory), "some-book", {"content.json": "{not json"}),
                "content (invalid JSON)",
            )

    def test_unparseable_book_json_is_reported_not_raised(self) -> None:
        # An agent mid-write must cost this book its row, not the whole queue.
        with tempfile.TemporaryDirectory() as directory:
            summary = self.needs(Path(directory), "some-book", {"book.json": "{not json"})
        self.assertIn("book.json (invalid JSON)", summary)

    def test_missing_sources_are_reported_as_research(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = self.needs(Path(directory), "some-book", {"book.json": "{}"})
        self.assertIn("research", summary)


class ManagedToolTests(unittest.TestCase):
    def test_a_missing_uv_explains_itself(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            bookflow.run_managed(["uv-that-is-not-installed"])
        message = str(caught.exception)
        self.assertIn("uv is not installed", message)
        self.assertIn("https://docs.astral.sh/uv/", message)

    def test_the_tool_exit_status_is_passed_through(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            bookflow.run_managed([sys.executable, "-c", "raise SystemExit(3)"])
        self.assertEqual(caught.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
