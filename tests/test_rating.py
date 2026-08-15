from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.rating import calculate_rating, rating_errors, rubric_errors, score_band


ROOT = Path(__file__).resolve().parent.parent


class RatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rubric = json.loads((ROOT / "config/rating.json").read_text(encoding="utf-8"))

    def rating(self, scores: list[float], total: float) -> dict:
        return {
            "score": total,
            "dimensions": [
                {"id": configured["id"], "score": score}
                for configured, score in zip(self.rubric["dimensions"], scores, strict=True)
            ],
        }

    @property
    def dimension_count(self) -> int:
        return len(self.rubric["dimensions"])

    def test_rubric_weights_total_one(self) -> None:
        self.assertEqual(rubric_errors(self.rubric), [])

    def test_weighted_score_uses_configured_weights_and_rounds_half_up(self) -> None:
        # Rubric v2 weights: .15, .2, .2, .1, .1, .1, .15. These scores total
        # exactly 6.45, so half-up rounding must give 6.5 (half-even would not).
        rating = self.rating([7.0, 6.5, 7.0, 6.0, 6.0, 6.0, 6.0], 6.5)
        self.assertEqual(calculate_rating(rating, self.rubric), 6.5)
        self.assertEqual(rating_errors(rating, self.rubric, require_complete=False), [])

    def test_stale_total_is_rejected(self) -> None:
        rating = self.rating([5.0] * self.dimension_count, 5.1)
        self.assertIn(
            "stored score 5.1 does not equal calculated 5.0",
            rating_errors(rating, self.rubric, require_complete=False),
        )

    def complete(self, **overrides) -> dict:
        rating = self.rating([5.0] * self.dimension_count, 5.0)
        rating.update({
            "rubric_version": self.rubric["schema_version"],
            "confidence": "medium", "summary": "A summary.", "basis": "inference",
        })
        for item in rating["dimensions"]:
            item.update({"rationale": "Because.", "source_ids": ["s1"]})
        rating.update(overrides)
        return rating

    def test_a_complete_rating_has_no_problems(self) -> None:
        self.assertEqual(rating_errors(self.complete(), self.rubric), [])

    def test_an_outdated_rubric_version_is_not_called_missing(self) -> None:
        problems = rating_errors(self.complete(rubric_version=1), self.rubric)
        self.assertIn("rubric_version does not match config/rating.json", problems)
        self.assertNotIn("rubric_version is missing", problems)

    def test_an_absent_rubric_version_is_called_missing(self) -> None:
        rating = self.complete()
        del rating["rubric_version"]
        self.assertEqual(rating_errors(rating, self.rubric), ["rubric_version is missing"])

    def test_messages_quote_the_configured_values_not_literals(self) -> None:
        # A rubric edit is the scenario these rules exist for, so the messages
        # must not hard-code the values they are checking against.
        rubric = {**self.rubric, "confidence": {"unsure": {}, "certain": {}}}
        self.assertIn("confidence must be one of: unsure, certain",
                      rating_errors(self.complete(), rubric))
        rubric = {**self.rubric, "scale": {**self.rubric["scale"], "maximum": 4}}
        self.assertTrue(any("score 5.0 is outside 0–4" in p
                            for p in rating_errors(self.complete(), rubric)),
                        rating_errors(self.complete(), rubric))

    def test_each_completeness_rule_reports_itself(self) -> None:
        cases = [
            ("basis", lambda r: r.__setitem__("basis", "synthesis"),
             "basis must be inference"),
            ("duplicate ids", lambda r: r["dimensions"][1].__setitem__(
                "id", r["dimensions"][0]["id"]), "dimension ids are not unique"),
            ("order", lambda r: r["dimensions"].reverse(),
             "dimensions must follow the order in config/rating.json"),
            ("rationale", lambda r: r["dimensions"][0].__setitem__("rationale", "TODO"),
             "rationale is incomplete"),
            ("sources", lambda r: r["dimensions"][0].__setitem__("source_ids", []),
             "has no supporting sources"),
            ("dimensions type", lambda r: r.__setitem__("dimensions", "not a list"),
             "dimensions must be a list"),
            ("missing dimension", lambda r: r["dimensions"].pop(),
             "missing dimensions: "),
            ("unknown dimension", lambda r: r["dimensions"].append(
                {**r["dimensions"][0], "id": "vibes"}), "unknown dimensions: vibes"),
        ]
        for name, break_it, expected in cases:
            with self.subTest(name):
                rating = self.complete()
                break_it(rating)
                problems = rating_errors(rating, self.rubric)
                self.assertTrue(any(expected in p for p in problems), (name, problems))

    def test_a_rubric_with_repeated_dimension_ids_is_rejected(self) -> None:
        dimensions = [dict(item) for item in self.rubric["dimensions"]]
        dimensions[1]["id"] = dimensions[0]["id"]
        self.assertIn("dimension ids are not unique",
                      rubric_errors({**self.rubric, "dimensions": dimensions}))

    def test_every_reachable_total_has_a_band(self) -> None:
        # score_band raises on a score between bands, so a rubric edit that
        # left a gap would crash ./bookflow rate for some books and not others.
        for score in range(0, 101):
            self.assertTrue(score_band(score / 10, self.rubric))

    def test_a_band_gap_is_reported_against_the_configured_precision(self) -> None:
        rubric = {**self.rubric, "score_bands": [
            {"label": "low", "minimum": 0, "maximum": 4.8},
            {"label": "high", "minimum": 5, "maximum": 10},
        ]}
        self.assertEqual(rubric_errors(rubric),
                         ["score_bands leave 1 reachable score(s) unlabelled: 4.9"])
        # The same bands are complete at whole-number precision.
        whole = {**rubric, "scale": {**rubric["scale"], "output_decimals": 0}}
        self.assertEqual(rubric_errors(whole), [])

    def test_component_scores_use_half_point_steps(self) -> None:
        rating = self.rating([5.1] + [5.0] * (self.dimension_count - 1), 5.0)
        self.assertTrue(any("not in 0.5-point increments" in item
                            for item in rating_errors(rating, self.rubric, require_complete=False)))


if __name__ == "__main__":
    unittest.main()
