"""Guardrails for the weekly relationship-led book discovery."""

from __future__ import annotations

import copy
import unittest

from scripts.validate_weekly_discovery import ValidationError, validate_discovery


def fixture_documents() -> tuple[dict, dict, dict]:
    catalog = {
        "entities": [
            {"id": "known-author", "kind": "author", "name": "Known Author"},
            {"id": "known-book", "kind": "book", "name": "Known Book",
             "author_ids": ["known-author"]},
        ]
    }
    queue = {"queue": [{"book_id": "known-book", "priority": 1,
                         "status": "done", "source": "user",
                         "added_at": "2026-01-01"}]}
    relationships = {"relationships": []}
    return catalog, queue, relationships


def valid_discovery() -> tuple[dict, dict, dict, dict, list[str]]:
    base_catalog, base_queue, base_relationships = fixture_documents()
    catalog = copy.deepcopy(base_catalog)
    catalog["entities"].extend([
        {"id": "new-author", "kind": "author", "name": "New Author"},
        {"id": "new-book", "kind": "book", "name": "New Book",
         "author_ids": ["new-author"],
         "path": "library/books/new-book/book.json", "state": "catalogued"},
    ])
    queue = copy.deepcopy(base_queue)
    queue["queue"].append({"book_id": "new-book", "priority": 2,
                            "status": "ready", "source": "discovery",
                            "added_at": "2026-09-06"})
    relationships = copy.deepcopy(base_relationships)
    relationships["relationships"].append({
        "id": "new-book-related-to-known-book",
        "source_id": "new-book",
        "target_id": "known-book",
        "type": "related-to",
    })
    manifest = {
        "book_id": "new-book",
        "title": "New Book",
        "author": "New Author",
        "relationship_id": "new-book-related-to-known-book",
        "related_book_id": "known-book",
        "rationale": "It extends a theme already represented in the library.",
        "sources": ["https://publisher.example/new-book"],
    }
    paths = [
        "data/catalog.json",
        "data/queue.json",
        "data/relationships.json",
        "library/authors/new-author/author.json",
        "library/books/new-book/book.json",
        "library/books/new-book/content.json",
    ]
    return catalog, queue, relationships, manifest, paths


class WeeklyDiscoveryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_catalog, self.base_queue, self.base_relationships = fixture_documents()

    def validate(self, *, mutate=lambda *_: None) -> str:
        catalog, queue, relationships, manifest, paths = valid_discovery()
        mutate(catalog, queue, relationships, manifest, paths)
        return validate_discovery(
            self.base_catalog, self.base_queue, self.base_relationships,
            catalog, queue, relationships, manifest, paths,
        )

    def test_accepts_one_related_discovered_book(self) -> None:
        self.assertEqual(self.validate(), "new-book")

    def test_rejects_more_than_one_new_book(self) -> None:
        def add_second(catalog, queue, *_):
            catalog["entities"].append({"id": "another-book", "kind": "book",
                                         "name": "Another Book"})
            queue["queue"].append({"book_id": "another-book", "source": "discovery"})

        with self.assertRaisesRegex(ValidationError, "exactly one new book"):
            self.validate(mutate=add_second)

    def test_rejects_a_duplicate_title(self) -> None:
        def duplicate_title(catalog, *_):
            next(item for item in catalog["entities"]
                 if item["id"] == "new-book")["name"] = " Known   Book "

        with self.assertRaisesRegex(ValidationError, "duplicates an existing title"):
            self.validate(mutate=duplicate_title)

    def test_requires_a_discovery_queue_entry(self) -> None:
        def make_user_queue(_, queue, *__):
            queue["queue"][-1]["source"] = "user"

        with self.assertRaisesRegex(ValidationError, "source=discovery"):
            self.validate(mutate=make_user_queue)

    def test_requires_a_relationship_to_an_existing_book(self) -> None:
        def relate_to_author(_, __, relationships, ___, ____):
            relationships["relationships"][0]["target_id"] = "known-author"

        with self.assertRaisesRegex(ValidationError, "existing book"):
            self.validate(mutate=relate_to_author)

    def test_rejects_changes_outside_the_new_scaffold(self) -> None:
        def add_unrelated_path(*args):
            args[-1].append("README.md")

        with self.assertRaisesRegex(ValidationError, "outside the discovery scaffold"):
            self.validate(mutate=add_unrelated_path)

    def test_manifest_must_match_the_discovery(self) -> None:
        def alter_manifest(_, __, ___, manifest, ____):
            manifest["related_book_id"] = "some-other-book"

        with self.assertRaisesRegex(ValidationError, "manifest relationship"):
            self.validate(mutate=alter_manifest)


if __name__ == "__main__":
    unittest.main()
