from __future__ import annotations

import unittest

from scripts.pronunciation import (
    phonemize_with_dictionary,
    pronunciation_is_current,
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


class FreshnessTests(unittest.TestCase):
    entries = [{
        "term": "Ada",
        "aliases": [],
        "case_sensitive": False,
        "phonemes": {"en-gb": "A"},
    }]

    def sidecar_with_signature(self) -> dict:
        return {
            "lang": "en-gb",
            "pronunciation_terms": ["Ada"],
            "pronunciation_entries_sha256": pronunciation_signature(
                ["Ada"], "en-gb", self.entries,
            ),
        }

    def test_matching_signature_is_current(self) -> None:
        self.assertTrue(pronunciation_is_current(
            "Ada wrote", self.sidecar_with_signature(), self.entries,
        ))

    def test_changed_phonemes_make_audio_stale(self) -> None:
        changed = [{**self.entries[0], "phonemes": {"en-gb": "B"}}]
        self.assertFalse(pronunciation_is_current(
            "Ada wrote", self.sidecar_with_signature(), changed,
        ))

    def test_legacy_sidecar_stays_current_when_no_entry_matches(self) -> None:
        sidecar = {"lang": "en-gb", "pronunciation_terms": []}
        self.assertTrue(pronunciation_is_current("Grace wrote", sidecar, self.entries))

    def test_legacy_sidecar_stales_when_script_contains_a_term(self) -> None:
        sidecar = {"lang": "en-gb", "pronunciation_terms": []}
        self.assertFalse(pronunciation_is_current("Ada wrote", sidecar, self.entries))


if __name__ == "__main__":
    unittest.main()
