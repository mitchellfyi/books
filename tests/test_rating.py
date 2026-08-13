from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.rating import calculate_rating, rating_errors, rubric_errors


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

    def test_rubric_weights_total_one(self) -> None:
        self.assertEqual(rubric_errors(self.rubric), [])

    def test_weighted_score_uses_configured_weights_and_one_decimal(self) -> None:
        rating = self.rating([7.5, 5.0, 7.0, 7.5, 5.5, 5.5], 6.4)
        self.assertEqual(calculate_rating(rating, self.rubric), 6.4)
        self.assertEqual(rating_errors(rating, self.rubric, require_complete=False), [])

    def test_stale_total_is_rejected(self) -> None:
        rating = self.rating([5.0] * 6, 5.1)
        self.assertIn(
            "stored score 5.1 does not equal calculated 5.0",
            rating_errors(rating, self.rubric, require_complete=False),
        )

    def test_component_scores_use_half_point_steps(self) -> None:
        rating = self.rating([5.1, 5.0, 5.0, 5.0, 5.0, 5.0], 5.0)
        self.assertTrue(any("not in 0.5-point increments" in item
                            for item in rating_errors(rating, self.rubric, require_complete=False)))


if __name__ == "__main__":
    unittest.main()
