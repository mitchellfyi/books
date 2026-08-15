from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_bookflow() -> types.ModuleType:
    """Import the extensionless bookflow script as a module."""
    source = ROOT.joinpath("bookflow").read_text(encoding="utf-8")
    module = types.ModuleType("bookflow_cli")
    module.__file__ = str(ROOT / "bookflow")
    sys.path.insert(0, str(ROOT))
    try:
        exec(compile(source, str(ROOT / "bookflow"), "exec"), module.__dict__)
    finally:
        sys.path.remove(str(ROOT))
    return module


bookflow = load_bookflow()


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
        for relative in ("templates", "config", "data/catalog.json", "data/queue.json"):
            source = ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        (root / "library/books").mkdir(parents=True)
        (root / "library/authors").mkdir(parents=True)

        original = bookflow.ROOT
        bookflow.ROOT = root
        bookflow.load_config.cache_clear()
        try:
            # init_book prints a research prompt; keep it out of the test run.
            with contextlib.redirect_stdout(io.StringIO()):
                bookflow.init_book(argparse.Namespace(
                    title=title, author=author, book_id=None, author_id=None,
                    force=True, note="", discovered=False))
        finally:
            bookflow.ROOT = original
            bookflow.load_config.cache_clear()
        return root / "library/books"

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


if __name__ == "__main__":
    unittest.main()
