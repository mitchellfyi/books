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

from fixtures import (
    FIXTURE_BOOK,
    bookflow,
    bookflow_at,
    copy_into,
    empty_repository,
    one_book_repository,
    read,
)


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


class InitRefusalTests(unittest.TestCase):
    """Every guardrail init has, and the words it refuses in.

    These are the messages a person meets when they mistype something, so the
    wording is the feature; mutation testing found all of them deletable
    without a test noticing.
    """

    CASES = [
        ({"title": "李白", "author": "Someone"},
         "--title must contain at least one letter or number"),
        ({"title": "A Book", "author": "李白"},
         "--author must contain at least one letter or number"),
        ({"title": "A Book", "author": "Someone", "book_id": "Not_Kebab"},
         "--book-id must be lowercase kebab-case; try 'not-kebab'"),
        ({"title": "A Book", "author": "Someone", "author_id": "Not_Kebab"},
         "--author-id must be lowercase kebab-case"),
        # Slugs to something, but the derived id does not: a surname with no
        # ASCII leaves 'poems-'.
        ({"title": "Poems", "author": "Bai 李白"},
         "Could not derive a usable book id"),
        ({"title": "Deep Work", "author": "Cal Newport"},
         "Book already exists"),
        ({"title": "Deep Work: Rules for Focused Success", "author": "Someone Else"},
         "looks like the same work"),
    ]

    def test_each_refusal_says_why(self) -> None:
        for fields, expected in self.CASES:
            with self.subTest(expected), tempfile.TemporaryDirectory() as directory:
                root = one_book_repository(Path(directory))
                arguments = {"book_id": None, "author_id": None, "force": False,
                             "note": "", "discovered": False, **fields}
                with bookflow_at(root), self.assertRaises(SystemExit) as caught:
                    with contextlib.redirect_stdout(io.StringIO()):
                        bookflow.init_book(argparse.Namespace(**arguments))
                self.assertIn(expected, str(caught.exception))

    def test_force_overrides_the_similar_title_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    bookflow.init_book(argparse.Namespace(
                        title="Deep Work: Rules for Focused Success", author="Someone Else",
                        book_id=None, author_id=None, force=True, note="", discovered=False))
            self.assertTrue((root / "library/books/deep-work-else").is_dir())


class QueueTests(unittest.TestCase):
    def queued(self, root: Path) -> list[dict]:
        return read(root / "data/queue.json")["queue"]

    def test_an_unknown_status_is_refused_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root), self.assertRaises(SystemExit) as caught:
                bookflow.cmd_queue(argparse.Namespace(set=[FIXTURE_BOOK, "sideways"]))
        self.assertIn("status must be one of: ready, in-progress, done, blocked",
                      str(caught.exception))

    def test_setting_a_book_that_is_not_queued_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root), self.assertRaises(SystemExit) as caught:
                bookflow.cmd_queue(argparse.Namespace(set=["ghost", "done"]))
        self.assertIn("not in queue: ghost", str(caught.exception))

    def test_a_status_change_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    bookflow.cmd_queue(argparse.Namespace(set=[FIXTURE_BOOK, "blocked"]))
            self.assertEqual([item["status"] for item in self.queued(root)], ["blocked"])

    def test_queueing_a_book_twice_leaves_one_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root):
                bookflow.queue_add(FIXTURE_BOOK, source="user", notes="second")
                entries = self.queued(root)
            self.assertEqual(len(entries), 1)
            self.assertNotIn("notes", entries[0])

    def test_a_new_book_goes_to_the_end_of_the_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root):
                bookflow.queue_add("another-book", source="discovery", notes="a note")
                entries = self.queued(root)
        self.assertEqual([e["book_id"] for e in entries], [FIXTURE_BOOK, "another-book"])
        self.assertEqual(entries[-1]["priority"], entries[0]["priority"] + 1)
        self.assertEqual(entries[-1]["notes"], "a note")


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

    def test_a_finished_book_needs_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            with bookflow_at(root):
                self.assertEqual(bookflow.book_needs(FIXTURE_BOOK),
                                 "nothing — ready to mark done")

    def test_a_draft_script_is_named_by_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            script = root / "library/books" / FIXTURE_BOOK / "scripts/30-seconds.md"
            script.write_text(script.read_text(encoding="utf-8").replace(
                "status: complete", "status: draft"), encoding="utf-8")
            with bookflow_at(root):
                summary = bookflow.book_needs(FIXTURE_BOOK)
        self.assertIn("scripts: 30-seconds", summary)
        self.assertNotIn("audio: 30-seconds", summary)  # a draft is not owed audio yet

    def test_a_complete_script_without_audio_is_named_by_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = one_book_repository(Path(directory))
            for media in (root / "library/books" / FIXTURE_BOOK / "audio").glob("30-seconds.*.mp3"):
                media.unlink()
            with bookflow_at(root):
                summary = bookflow.book_needs(FIXTURE_BOOK)
        self.assertIn("audio: 30-seconds", summary)

    def test_missing_sources_are_reported_as_research(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = self.needs(Path(directory), "some-book", {"book.json": "{}"})
        self.assertIn("research", summary)


class PortTests(unittest.TestCase):
    def test_a_usable_port_is_accepted(self) -> None:
        self.assertEqual(bookflow.port_number("8042"), 8042)
        self.assertEqual(bookflow.port_number("0"), 0)  # any free port

    def test_a_port_outside_the_range_is_a_usage_error(self) -> None:
        # Binding one raises OverflowError, which serve's OSError handler
        # cannot catch: argparse should refuse it before that.
        for value in ("99999", "-1", "65536"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                bookflow.port_number(value)

    def test_a_non_numeric_port_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            bookflow.port_number("abc")


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
