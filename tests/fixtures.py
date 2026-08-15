"""Throwaway repositories, and pointing the tooling at them.

Not a test module (unittest collects `test*.py`), so importing it does not
run anything. It loads `bookflow` and `scripts/check.py` once, the way each
is loaded in real use, and hands the test modules a repository they can break
without touching the library.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check  # noqa: E402  (needs scripts/ on the path, as uv run gives it)

# The one book every fixture repository is built around: complete, rated,
# reviewed and voiced, so it exercises the strictest rules check has.
FIXTURE_BOOK = "deep-work-newport"

EMPTY_DATA = {
    "data/catalog.json": {"$schema": "../schemas/catalog.schema.json",
                          "schema_version": 1, "entities": []},
    "data/queue.json": {"$schema": "../schemas/queue.schema.json",
                        "schema_version": 1, "queue": []},
    "data/relationships.json": {"$schema": "../schemas/relationships.schema.json",
                                "schema_version": 1, "relationships": []},
}


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


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_into(root: Path, *relatives: str) -> None:
    """Copy real repository files into a throwaway root, keeping their paths."""
    for relative in relatives:
        source, target = ROOT / relative, root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def empty_repository(root: Path, *extra: str) -> Path:
    """The shared files, empty data, and nowhere to put a book yet."""
    copy_into(root, "templates", "config", "schemas", "taxonomy", *extra)
    for relative, document in EMPTY_DATA.items():
        write(root / relative, document)
    (root / "library/books").mkdir(parents=True)
    (root / "library/authors").mkdir(parents=True)
    return root


def one_book_repository(root: Path, book_id: str = FIXTURE_BOOK, *extra: str) -> Path:
    """A valid single-book repository, assembled from the real one.

    Audio media are stand-ins: the committed sidecars carry the provenance,
    and check only looks for a matching file beside them, so the fixture does
    not depend on locally generated audio.
    """
    empty_repository(root, *extra)
    source = ROOT / "library/books" / book_id
    target = root / "library/books" / book_id
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)

    book = read(source / "book.json")
    for author_id in book["author_ids"]:
        shutil.copytree(ROOT / "library/authors" / author_id,
                        root / "library/authors" / author_id)

    for sidecar in (target / "audio").glob("*.json"):
        level, voice, _ = sidecar.name.split(".")
        (target / "audio" / f"{level}.{voice}.{read(sidecar)['output_format']}").touch()

    keep = {book_id, *book["author_ids"]}
    catalog = read(ROOT / "data/catalog.json")
    catalog["entities"] = [e for e in catalog["entities"] if e["id"] in keep]
    write(root / "data/catalog.json", catalog)

    relationships = read(ROOT / "data/relationships.json")
    relationships["relationships"] = [r for r in relationships["relationships"]
                                      if {r["source_id"], r["target_id"]} <= keep]
    write(root / "data/relationships.json", relationships)
    write(root / "data/queue.json", {
        "$schema": "../schemas/queue.schema.json", "schema_version": 1,
        "queue": [{"book_id": book_id, "priority": 1, "status": "done",
                   "source": "user", "added_at": "2026-01-01"}],
    })
    return root


@contextlib.contextmanager
def bookflow_at(root: Path):
    """Point the CLI at a throwaway repository for the duration of a test.

    load_config caches by file name, not by root, so the cache is cleared on
    the way in and out; leaving it warm would serve one test's config to the
    next.
    """
    original = bookflow.ROOT
    bookflow.ROOT = root
    bookflow.load_config.cache_clear()
    try:
        yield root
    finally:
        bookflow.ROOT = original
        bookflow.load_config.cache_clear()


@contextlib.contextmanager
def check_at(root: Path):
    """Point the validator at a throwaway repository, with its state reset."""
    original = check.ROOT
    check.ROOT = root
    reset_check()
    try:
        yield root
    finally:
        check.ROOT = original
        reset_check()


def reset_check() -> None:
    check.errors.clear()
    check.warnings.clear()
    check.schema_validator.cache_clear()
    check.load_json_once.cache_clear()
