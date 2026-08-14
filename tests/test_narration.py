from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.narration import parse_front_matter, word_count


def write_script(directory: str, text: str) -> Path:
    path = Path(directory) / "script.md"
    path.write_text(text, encoding="utf-8")
    return path


class FrontMatterTests(unittest.TestCase):
    def test_values_are_typed_and_body_is_stripped(self) -> None:
        text = (
            "---\n"
            "book_id: deep-work-newport\n"
            "target_words: 2250\n"
            "status: complete\n"
            "reviewed: true\n"
            "title: 'Deep Work'\n"
            "---\n"
            "\nThe body.\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, text))
        self.assertEqual(meta["book_id"], "deep-work-newport")
        self.assertEqual(meta["target_words"], 2250)
        self.assertEqual(meta["status"], "complete")
        self.assertIs(meta["reviewed"], True)
        self.assertEqual(meta["title"], "Deep Work")
        self.assertEqual(body, "The body.")

    def test_missing_front_matter_returns_whole_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, "Just prose.\n"))
        self.assertEqual(meta, {})
        self.assertEqual(body, "Just prose.\n")

    def test_unterminated_front_matter_returns_whole_text(self) -> None:
        text = "---\nstatus: draft\nNo closing fence.\n"
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, text))
        self.assertEqual(meta, {})
        self.assertEqual(body, text)


class WordCountTests(unittest.TestCase):
    def test_counts_plain_words(self) -> None:
        self.assertEqual(word_count("Attention is the new capital."), 5)

    def test_markdown_syntax_does_not_count(self) -> None:
        self.assertEqual(word_count("# Heading\n\n**Bold** and _quiet_ words."), 5)

    def test_link_text_counts_but_url_does_not(self) -> None:
        self.assertEqual(word_count("See [the study](https://example.org/x) today."), 4)


if __name__ == "__main__":
    unittest.main()
