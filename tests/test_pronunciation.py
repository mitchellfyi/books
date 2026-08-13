from __future__ import annotations

import unittest

from scripts.pronunciation import (
    phonemize_with_dictionary,
    pronunciation_signature,
    pronunciation_terms_in_text,
)


def ordinary(text: str, _lang: str) -> str:
    return f"<{text.strip()}>" if text.strip() else ""


class PronunciationTests(unittest.TestCase):
    def test_replaces_exact_term_without_matching_part_of_word(self) -> None:
        entries = [{
            "term": "Ada",
            "aliases": [],
            "case_sensitive": False,
            "phonemes": {"en-gb": "A"},
        }]
        result, used = phonemize_with_dictionary(
            "Ada and adaptable", "en-gb", entries, ordinary,
        )
        self.assertEqual(result, "A <and adaptable>")
        self.assertEqual(used, ["Ada"])

    def test_longest_matching_name_wins(self) -> None:
        entries = [
            {
                "term": "Ada",
                "aliases": [],
                "case_sensitive": False,
                "phonemes": {"en-gb": "A"},
            },
            {
                "term": "Ada Lovelace",
                "aliases": [],
                "case_sensitive": False,
                "phonemes": {"en-gb": "L"},
            },
        ]
        result, used = phonemize_with_dictionary(
            "Ada Lovelace wrote", "en-gb", entries, ordinary,
        )
        self.assertEqual(result, "L <wrote>")
        self.assertEqual(used, ["Ada Lovelace"])

    def test_rejects_symbols_outside_tokenizer_vocabulary(self) -> None:
        entries = [{
            "term": "Ada",
            "aliases": [],
            "case_sensitive": False,
            "phonemes": {"en-gb": "AZ"},
        }]
        with self.assertRaisesRegex(ValueError, "unsupported symbols"):
            phonemize_with_dictionary(
                "Ada", "en-gb", entries, ordinary, valid_symbols={"A"},
            )

    def test_freshness_terms_respect_case_and_longest_match(self) -> None:
        entries = [
            {
                "term": "Cal",
                "aliases": [],
                "case_sensitive": True,
                "phonemes": {"en-gb": "C"},
            },
            {
                "term": "Cal Newport",
                "aliases": [],
                "case_sensitive": False,
                "phonemes": {"en-gb": "N"},
            },
        ]
        self.assertEqual(
            pronunciation_terms_in_text("Cal Newport calculated", "en-gb", entries),
            ["Cal Newport"],
        )

    def test_signature_ignores_unrelated_entries(self) -> None:
        entries = [{
            "term": "Ada",
            "aliases": [],
            "case_sensitive": False,
            "phonemes": {"en-gb": "A"},
        }]
        before = pronunciation_signature(["Ada"], "en-gb", entries)
        entries.append({
            "term": "Grace",
            "aliases": [],
            "case_sensitive": False,
            "phonemes": {"en-gb": "G"},
        })
        self.assertEqual(before, pronunciation_signature(["Ada"], "en-gb", entries))


if __name__ == "__main__":
    unittest.main()
