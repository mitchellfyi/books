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
import tempfile
import unittest
from pathlib import Path

import check
from fixtures import bookflow, bookflow_at, check_at, empty_repository


def scaffold(root: Path, title: str, author: str) -> None:
    """Run init in an otherwise empty repository built from the real shared files."""
    empty_repository(root)
    with bookflow_at(root):
        with contextlib.redirect_stdout(io.StringIO()):
            bookflow.init_book(argparse.Namespace(
                title=title, author=author, book_id=None, author_id=None,
                force=False, note="", discovered=False))


class ScaffoldTests(unittest.TestCase):
    def test_a_freshly_initialised_book_passes_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scaffold(root, "A Brand New Book", "Fresh Author")
            with check_at(root):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = check.main(["--quiet"])
                errors, warnings = list(check.errors), list(check.warnings)
        self.assertEqual((status, errors, warnings), (0, [], []))


if __name__ == "__main__":
    unittest.main()
