from __future__ import annotations

import unittest

from scripts.pronunciation import (
    phonemize_with_dictionary,
    pronunciation_is_current,
    pronunciation_signature,
    pronunciation_terms_in_text,
    spelling_matcher,
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

    def test_a_possessive_still_reports_the_plain_term(self) -> None:
        # The freshness scan and the phonemiser share one pattern; recording
        # "Ada's" as the applied term would stale the audio on every run.
        entries = [{
            "term": "Ada",
            "aliases": [],
            "case_sensitive": False,
            "phonemes": {"en-gb": "A"},
        }]
        self.assertEqual(pronunciation_terms_in_text("Ada's work", "en-gb", entries), ["Ada"])

    def test_a_language_the_dictionary_does_not_cover_has_no_matcher(self) -> None:
        entries = [{
            "term": "Ada", "aliases": [], "case_sensitive": False,
            "phonemes": {"en-gb": "A"},
        }]
        self.assertIsNone(spelling_matcher("en-us", entries))
        self.assertEqual(pronunciation_terms_in_text("Ada", "en-us", entries), [])

    def test_a_term_whose_entry_has_gone_changes_the_signature(self) -> None:
        # The sidecar names terms it applied; if one no longer has an entry for
        # that language the audio cannot still be current.
        entries = [{
            "term": "Ada", "aliases": [], "case_sensitive": False,
            "phonemes": {"en-gb": "A"},
        }]
        present = pronunciation_signature(["Ada"], "en-gb", entries)
        self.assertNotEqual(present, pronunciation_signature(["Ada"], "en-gb", []))
        self.assertNotEqual(present, pronunciation_signature(["Ada"], "en-us", entries))

    def test_an_empty_dictionary_phonemises_the_whole_text(self) -> None:
        applied, used = phonemize_with_dictionary("Ada wrote", "en-gb", [], ordinary)
        self.assertEqual((applied, used), ("<Ada wrote>", []))

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


class PossessiveTests(unittest.TestCase):
    def phonemes_for(self, text: str, custom: str) -> str:
        entries = [{
            "term": "Name", "aliases": [], "case_sensitive": False,
            "phonemes": {"en-gb": custom},
        }]
        return phonemize_with_dictionary(text, "en-gb", entries, ordinary)[0]

    def test_voiceless_ending_takes_s(self) -> None:
        # Proust -> pɹˈuːst: without this the stray "'s" is read as "ess".
        self.assertEqual(self.phonemes_for("Name's book", "pɹˈuːst"), "pɹˈuːsts <book>")

    def test_voiced_ending_takes_z(self) -> None:
        self.assertEqual(self.phonemes_for("Name's book", "tʃaldˈiːni"), "tʃaldˈiːniz <book>")

    def test_sibilant_ending_takes_iz(self) -> None:
        self.assertEqual(self.phonemes_for("Name's book", "hˈɒɹəs"), "hˈɒɹəsɪz <book>")

    def test_trailing_length_and_stress_marks_are_ignored(self) -> None:
        self.assertEqual(self.phonemes_for("Name's book", "bʊədjˈɜː"), "bʊədjˈɜːz <book>")

    def test_typographic_apostrophe_is_matched(self) -> None:
        self.assertEqual(self.phonemes_for("Name’s book", "ɹˈɪlkə"), "ɹˈɪlkəz <book>")

    def test_text_before_a_match_is_kept(self) -> None:
        self.assertEqual(self.phonemes_for("Long before Name arrived", "ɹˈɪlkə"),
                         "<Long before> ɹˈɪlkə <arrived>")

    def test_plain_term_is_unchanged(self) -> None:
        self.assertEqual(self.phonemes_for("Name wrote", "ɹˈɪlkə"), "ɹˈɪlkə <wrote>")

    def test_case_sensitive_term_keeps_its_possessive_rule(self) -> None:
        entries = [{
            "term": "Cal", "aliases": [], "case_sensitive": True,
            "phonemes": {"en-gb": "kˈæl"},
        }]
        applied, used = phonemize_with_dictionary("Cal's desk", "en-gb", entries, ordinary)
        self.assertEqual(applied, "kˈælz <desk>")
        self.assertEqual(used, ["Cal"])
        # The wrong case is skipped, possessive and all.
        skipped, unused = phonemize_with_dictionary("cal's desk", "en-gb", entries, ordinary)
        self.assertEqual(skipped, "<cal's desk>")
        self.assertEqual(unused, [])


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

    def test_a_legacy_sidecar_that_applied_terms_is_always_stale(self) -> None:
        # No signature to compare against, but it recorded terms whose entries
        # may since have changed or gone: it cannot be shown to be current.
        sidecar = {"lang": "en-gb", "pronunciation_terms": ["Ada"]}
        self.assertFalse(pronunciation_is_current("Grace wrote", sidecar, self.entries))

    def test_legacy_sidecar_stays_current_when_no_entry_matches(self) -> None:
        sidecar = {"lang": "en-gb", "pronunciation_terms": []}
        self.assertTrue(pronunciation_is_current("Grace wrote", sidecar, self.entries))

    def test_legacy_sidecar_stales_when_script_contains_a_term(self) -> None:
        sidecar = {"lang": "en-gb", "pronunciation_terms": []}
        self.assertFalse(pronunciation_is_current("Ada wrote", sidecar, self.entries))


if __name__ == "__main__":
    unittest.main()
