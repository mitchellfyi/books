from __future__ import annotations

import unittest

from scripts.pronunciation import phonemize_with_dictionary


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


if __name__ == "__main__":
    unittest.main()
