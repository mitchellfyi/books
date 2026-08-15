"""`./bookflow build` assembles dist/, and `./bookflow serve` builds first.

Audio is nearly all of dist by volume and changes only when a book is
re-voiced, so a rebuild syncs it rather than recopying it. These hold both
halves of that bargain: an unchanged library must not rewrite a byte, and
what the library no longer produces must not survive in the built site.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fixtures import FIXTURE_BOOK, bookflow, bookflow_at, one_book_repository


def build(root: Path) -> str:
    with bookflow_at(root):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            bookflow.build_app()
    return output.getvalue()


def fingerprint(dist: Path) -> dict[str, bytes]:
    return {str(p.relative_to(dist)): p.read_bytes()
            for p in sorted(dist.rglob("*")) if p.is_file()}


def repository(root: Path) -> Path:
    one_book_repository(root, FIXTURE_BOOK, "app")
    # Stand-in audio is zero bytes; give it content so a copy is observable.
    for audio in (root / "library/books" / FIXTURE_BOOK / "audio").glob("*.mp3"):
        audio.write_bytes(b"audio for " + audio.name.encode())
    return root


class BuildTests(unittest.TestCase):
    def test_the_site_carries_the_app_the_data_and_the_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            build(root)
            built = fingerprint(root / "dist")
            library = json.loads((root / "dist/data/library.json").read_text(encoding="utf-8"))
        for asset in ("index.html", "app.js", "styles.css", "data/library.json"):
            self.assertIn(asset, built)
        self.assertEqual([book["id"] for book in library["books"]], [FIXTURE_BOOK])
        self.assertEqual(len([name for name in built if name.endswith(".mp3")]), 4)
        # Every audio url in the data must resolve to a file in the site.
        for book in library["books"]:
            for script in book["scripts"].values():
                for variant in script["audio"].values():
                    self.assertIn(variant["url"], built)

    def test_rebuilding_an_unchanged_library_writes_no_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            build(root)
            before = fingerprint(root / "dist")
            stamps = self.audio_stamps(root)
            report = build(root)
            after = fingerprint(root / "dist")
            # Untouched, not merely identical: a rewrite would move the mtime.
            self.assertEqual(self.audio_stamps(root), stamps)
        self.assertEqual(before, after)
        self.assertNotIn("written", report)

    @staticmethod
    def audio_stamps(root: Path) -> dict[str, int]:
        return {str(p): p.stat().st_mtime_ns for p in (root / "dist/audio").rglob("*.mp3")}

    def test_a_re_voiced_level_is_copied_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            build(root)
            source = root / "library/books" / FIXTURE_BOOK / "audio/30-seconds.bf_emma.mp3"
            source.write_bytes(b"a different recording entirely")
            report = build(root)
            built = (root / "dist/audio" / FIXTURE_BOOK / "30-seconds.bf_emma.mp3").read_bytes()
        self.assertEqual(built, b"a different recording entirely")
        self.assertIn("1 written", report)

    def test_audio_the_library_no_longer_produces_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            build(root)
            ghost = root / "dist/audio/a-book-that-left"
            ghost.mkdir(parents=True)
            (ghost / "30-seconds.bf_emma.mp3").write_bytes(b"stale")
            retired = root / "dist/audio" / FIXTURE_BOOK / "30-seconds.retired_voice.mp3"
            retired.write_bytes(b"stale")
            report = build(root)
            kept = root / "dist/audio" / FIXTURE_BOOK / "30-seconds.bf_emma.mp3"
            self.assertFalse(ghost.exists(), "an emptied book directory should go too")
            self.assertFalse(retired.exists())
            self.assertTrue(kept.exists())
        self.assertIn("2 removed", report)

    def test_a_stale_app_asset_does_not_survive_a_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            build(root)
            (root / "dist/leftover.html").write_text("old", encoding="utf-8")
            build(root)
            self.assertFalse((root / "dist/leftover.html").exists())

    def test_a_book_without_content_is_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            (root / "library/books" / FIXTURE_BOOK / "content.json").unlink()
            build(root)
            library = json.loads((root / "dist/data/library.json").read_text(encoding="utf-8"))
        self.assertEqual(library["books"], [])

    def test_a_book_missing_a_required_field_names_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(Path(directory))
            path = root / "library/books" / FIXTURE_BOOK / "book.json"
            book = json.loads(path.read_text(encoding="utf-8"))
            del book["bibliography"]
            path.write_text(json.dumps(book), encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                build(root)
        message = str(caught.exception)
        self.assertIn("bibliography", message)
        self.assertIn("./bookflow check", message)


class SyncAudioTests(unittest.TestCase):
    def test_an_identical_destination_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "a.mp3"
            destination = Path(directory) / "b.mp3"
            source.write_bytes(b"same")
            self.assertTrue(bookflow.sync_audio(source, destination))
            self.assertFalse(bookflow.sync_audio(source, destination))

    def test_a_different_size_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "a.mp3"
            destination = Path(directory) / "b.mp3"
            source.write_bytes(b"same")
            bookflow.sync_audio(source, destination)
            source.write_bytes(b"longer than before")
            self.assertTrue(bookflow.sync_audio(source, destination))
            self.assertEqual(destination.read_bytes(), b"longer than before")


if __name__ == "__main__":
    unittest.main()
