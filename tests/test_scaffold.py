"""The scaffold `./bookflow init` writes must satisfy the schemas `check` enforces.

templates/, schemas/ and config/audio.json are edited independently, and
nothing else notices when they drift: `check` never looks at templates/, and
`init` never validates what it copied. An agent would meet the mismatch as a
wall of schema violations on a book it had not written yet.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check  # noqa: E402
from test_bookflow import bookflow, copy_into, repository_at  # noqa: E402
from test_check import repository_at as checking  # noqa: E402

EMPTY = {
    "data/catalog.json": {"$schema": "../schemas/catalog.schema.json",
                          "schema_version": 1, "entities": []},
    "data/queue.json": {"$schema": "../schemas/queue.schema.json",
                        "schema_version": 1, "queue": []},
    "data/relationships.json": {"$schema": "../schemas/relationships.schema.json",
                                "schema_version": 1, "relationships": []},
}


def scaffold(root: Path, title: str, author: str) -> None:
    """Run init in an otherwise empty repository built from the real shared files."""
    copy_into(root, "templates", "config", "schemas", "taxonomy")
    for relative, document in EMPTY.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (root / "library/books").mkdir(parents=True)
    (root / "library/authors").mkdir(parents=True)
    with repository_at(root):
        with contextlib.redirect_stdout(io.StringIO()):
            bookflow.init_book(argparse.Namespace(
                title=title, author=author, book_id=None, author_id=None,
                force=False, note="", discovered=False))


class ScaffoldTests(unittest.TestCase):
    def test_a_freshly_initialised_book_passes_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scaffold(root, "A Brand New Book", "Fresh Author")
            with checking(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = check.main(["--quiet"])
                errors, warnings = list(check.errors), list(check.warnings)
        self.assertEqual((status, errors, warnings), (0, [], []))


if __name__ == "__main__":
    unittest.main()
