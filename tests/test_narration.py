from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.narration import (
    chunked_paragraphs,
    parse_front_matter,
    spoken_text,
    word_count,
)


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

    def test_a_front_matter_line_without_a_colon_is_ignored(self) -> None:
        text = "---\nstatus: complete\njust a stray line\n---\n\nThe body.\n"
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, text))
        self.assertEqual(meta, {"status": "complete"})
        self.assertEqual(body, "The body.")

    def test_missing_front_matter_returns_whole_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, "Just prose.\n"))
        self.assertEqual(meta, {})
        self.assertEqual(body, "Just prose.\n")

    def test_a_rule_in_the_body_is_not_mistaken_for_front_matter(self) -> None:
        # Front matter is only front matter at the very top; a --- line further
        # down is prose, and swallowing everything above it would lose the text.
        text = "An opening line.\n\n---\n\nAnd more after the rule.\n"
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, text))
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_unterminated_front_matter_returns_whole_text(self) -> None:
        text = "---\nstatus: draft\nNo closing fence.\n"
        with tempfile.TemporaryDirectory() as directory:
            meta, body = parse_front_matter(write_script(directory, text))
        self.assertEqual(meta, {})
        self.assertEqual(body, text)


class SpokenTextTests(unittest.TestCase):
    def test_markdown_syntax_is_removed(self) -> None:
        self.assertEqual(
            spoken_text("# Heading\n\n**Bold** and _quiet_ words."),
            "Heading\n\nBold and quiet words.",
        )

    def test_link_text_survives_and_the_url_does_not(self) -> None:
        self.assertEqual(
            spoken_text("See [the study](https://example.org/x) today."),
            "See the study today.",
        )

    def test_list_markers_are_not_spoken(self) -> None:
        self.assertEqual(spoken_text("- first point\n2. second point"),
                         "first point\nsecond point")

    def test_paragraph_breaks_survive_for_chunking(self) -> None:
        self.assertEqual(spoken_text("One.\n\nTwo."), "One.\n\nTwo.")


class WordCountTests(unittest.TestCase):
    def test_counts_plain_words(self) -> None:
        self.assertEqual(word_count("Attention is the new capital."), 5)

    def test_markdown_syntax_does_not_count(self) -> None:
        self.assertEqual(word_count("# Heading\n\n**Bold** and _quiet_ words."), 5)

    def test_link_text_counts_but_url_does_not(self) -> None:
        self.assertEqual(word_count("See [the study](https://example.org/x) today."), 4)

    def test_counts_only_what_is_spoken(self) -> None:
        # A bullet marker is punctuation on the page and silence in the ear;
        # counting it would let a script pass its target on unspoken characters.
        self.assertEqual(word_count("- first point\n- second point"), 4)


class ChunkedParagraphTests(unittest.TestCase):
    def test_one_list_of_chunks_per_paragraph(self) -> None:
        self.assertEqual(
            chunked_paragraphs("First one. First two.\n\nSecond one."),
            [["First one. First two."], ["Second one."]],
        )

    def test_sentences_pack_up_to_the_character_limit(self) -> None:
        text = "Aaa bbb ccc. Ddd eee fff. Ggg hhh iii."
        self.assertEqual(
            chunked_paragraphs(text, max_chars=26),
            [["Aaa bbb ccc. Ddd eee fff.", "Ggg hhh iii."]],
        )

    def test_a_sentence_longer_than_the_limit_is_kept_whole(self) -> None:
        # Splitting mid-sentence would break the phrasing the model needs, so
        # an over-long sentence travels alone rather than being cut.
        self.assertEqual(
            chunked_paragraphs("Short. A single very long sentence indeed.", max_chars=10),
            [["Short.", "A single very long sentence indeed."]],
        )

    def test_blank_input_produces_no_chunks(self) -> None:
        self.assertEqual(chunked_paragraphs("   \n\n  "), [])


if __name__ == "__main__":
    unittest.main()
