#!/usr/bin/env python3
"""Validate the deliberately narrow output of the weekly discovery agent."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    """The agent changed more, or less, than one valid discovery."""


def keyed(items: list[dict[str, Any]], field: str = "id") -> dict[str, dict[str, Any]]:
    return {item[field]: item for item in items}


def normal_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def unchanged(base: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]],
              label: str) -> None:
    missing = sorted(base.keys() - current.keys())
    altered = sorted(key for key, value in base.items()
                     if key in current and current[key] != value)
    if missing or altered:
        details = ", ".join(missing + altered)
        raise ValidationError(f"existing {label} entries changed: {details}")


def validate_discovery(
    base_catalog: dict[str, Any],
    base_queue: dict[str, Any],
    base_relationships: dict[str, Any],
    catalog: dict[str, Any],
    queue: dict[str, Any],
    relationships: dict[str, Any],
    manifest: dict[str, Any],
    changed_paths: list[str],
) -> str:
    base_entities = keyed(base_catalog["entities"])
    entities = keyed(catalog["entities"])
    unchanged(base_entities, entities, "catalogue")

    new_entity_ids = entities.keys() - base_entities.keys()
    new_books = [entities[item_id] for item_id in new_entity_ids
                 if entities[item_id].get("kind") == "book"]
    if len(new_books) != 1:
        raise ValidationError("the run must add exactly one new book")
    book = new_books[0]
    book_id = book["id"]

    existing_titles = {
        normal_title(title)
        for item in base_entities.values()
        if item.get("kind") == "book"
        for title in [item["name"], *item.get("aliases", [])]
    }
    if normal_title(book["name"]) in existing_titles:
        raise ValidationError("the new book duplicates an existing title")

    base_queue_items = keyed(base_queue["queue"], "book_id")
    queue_items = keyed(queue["queue"], "book_id")
    unchanged(base_queue_items, queue_items, "queue")
    new_queue_ids = queue_items.keys() - base_queue_items.keys()
    if new_queue_ids != {book_id}:
        raise ValidationError("the run must add exactly one queue entry for the new book")
    queue_entry = queue_items[book_id]
    if queue_entry.get("source") != "discovery":
        raise ValidationError("the new queue entry must use source=discovery")
    if queue_entry.get("status") != "ready":
        raise ValidationError("the new queue entry must be ready")

    base_relations = keyed(base_relationships["relationships"])
    current_relations = keyed(relationships["relationships"])
    unchanged(base_relations, current_relations, "relationship")
    added_relations = [current_relations[item_id]
                       for item_id in current_relations.keys() - base_relations.keys()]
    if not added_relations:
        raise ValidationError("the run must add a relationship for the new book")
    if any(book_id not in {item.get("source_id"), item.get("target_id")}
           for item in added_relations):
        raise ValidationError("every new relationship must involve the new book")

    base_book_ids = {item_id for item_id, item in base_entities.items()
                     if item.get("kind") == "book"}
    related = []
    for item in added_relations:
        other = item["target_id"] if item["source_id"] == book_id else item["source_id"]
        if other in base_book_ids and item.get("type") not in {"written-by", "coauthored-with"}:
            related.append((item, other))
    if not related:
        raise ValidationError("the new book must have a topical relationship to an existing book")

    required_manifest = {
        "book_id", "title", "author", "relationship_id", "related_book_id",
        "rationale", "sources",
    }
    missing_fields = sorted(required_manifest - manifest.keys())
    if missing_fields:
        raise ValidationError(f"manifest is missing: {', '.join(missing_fields)}")
    if manifest["book_id"] != book_id or normal_title(manifest["title"]) != normal_title(book["name"]):
        raise ValidationError("manifest book does not match the discovery")
    relation_matches = any(
        item["id"] == manifest["relationship_id"] and other == manifest["related_book_id"]
        for item, other in related
    )
    if not relation_matches:
        raise ValidationError("manifest relationship does not match the discovery")
    author_names = {
        entities[author_id]["name"] for author_id in book.get("author_ids", [])
        if author_id in entities and entities[author_id].get("kind") == "author"
    }
    if manifest["author"] not in author_names:
        raise ValidationError("manifest author does not match the book")
    if not isinstance(manifest["rationale"], str) or not manifest["rationale"].strip():
        raise ValidationError("manifest rationale must explain the relationship")
    sources = manifest["sources"]
    if (not isinstance(sources, list) or not sources
            or any(not isinstance(source, str) or not source.startswith("https://")
                   for source in sources)):
        raise ValidationError("manifest sources must contain at least one HTTPS URL")

    new_author_ids = {
        item_id for item_id in new_entity_ids if entities[item_id].get("kind") == "author"
    }
    allowed_data = {"data/catalog.json", "data/queue.json", "data/relationships.json"}
    unexpected = []
    for path in changed_paths:
        allowed = (
            path in allowed_data
            or path.startswith(f"library/books/{book_id}/")
            or any(path.startswith(f"library/authors/{author_id}/")
                   for author_id in new_author_ids)
        )
        if not allowed:
            unexpected.append(path)
    if unexpected:
        raise ValidationError(
            "changes outside the discovery scaffold: " + ", ".join(sorted(unexpected))
        )
    if not allowed_data.issubset(changed_paths):
        raise ValidationError("the discovery must update catalogue, queue, and relationships")
    if not any(path.startswith(f"library/books/{book_id}/") for path in changed_paths):
        raise ValidationError("the discovery did not create the new book scaffold")

    return book_id


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_at_revision(root: Path, revision: str, path: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=root, check=True,
        text=True, capture_output=True,
    )
    return json.loads(result.stdout)


def changed_paths(root: Path, revision: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", revision, "--"],
        cwd=root, check=True, text=True, capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="Git revision before discovery")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    book_id = validate_discovery(
        load_at_revision(root, args.base, "data/catalog.json"),
        load_at_revision(root, args.base, "data/queue.json"),
        load_at_revision(root, args.base, "data/relationships.json"),
        load(root / "data/catalog.json"),
        load(root / "data/queue.json"),
        load(root / "data/relationships.json"),
        load(args.manifest),
        changed_paths(root, args.base),
    )
    print(f"Validated weekly discovery: {book_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
