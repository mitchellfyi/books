"""Shared deterministic calculation and validation for reputation-blind book ratings."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def calculate_rating(rating: dict, rubric: dict) -> float:
    """Return the weighted score rounded to the configured decimal places."""
    scores = {item["id"]: Decimal(str(item["score"])) for item in rating["dimensions"]}
    total = sum(
        scores[item["id"]] * Decimal(str(item["weight"]))
        for item in rubric["dimensions"]
    )
    places = rubric["scale"]["output_decimals"]
    quantum = Decimal(1).scaleb(-places)
    return float(total.quantize(quantum, rounding=ROUND_HALF_UP))


def rating_errors(
    rating: object,
    rubric: dict,
    *,
    check_total: bool = True,
    require_complete: bool = True,
) -> list[str]:
    """Check rules that JSON Schema cannot express cleanly."""
    if not isinstance(rating, dict):
        return ["rating is missing"]

    problems: list[str] = []
    if rating.get("rubric_version") not in (None, rubric.get("schema_version")):
        problems.append("rubric_version does not match config/rating.json")
    if require_complete:
        if rating.get("rubric_version") != rubric.get("schema_version"):
            problems.append("rubric_version is missing")
        if rating.get("confidence") not in rubric.get("confidence", {}):
            problems.append("confidence must be low, medium, or high")
        if not isinstance(rating.get("summary"), str) or not rating["summary"].strip() \
                or "TODO" in rating["summary"]:
            problems.append("summary is incomplete")
        if rating.get("basis") != "inference":
            problems.append("basis must be inference")
    configured = [item["id"] for item in rubric["dimensions"]]
    dimensions = rating.get("dimensions", [])
    if not isinstance(dimensions, list):
        return problems + ["dimensions must be a list"]
    actual = [item.get("id") for item in dimensions if isinstance(item, dict)]
    if len(actual) != len(set(actual)):
        problems.append("dimension ids are not unique")
    missing = [item for item in configured if item not in actual]
    extra = [item for item in actual if item not in configured]
    if missing:
        problems.append("missing dimensions: " + ", ".join(missing))
    if extra:
        problems.append("unknown dimensions: " + ", ".join(str(item) for item in extra))
    if not missing and not extra and actual != configured:
        problems.append("dimensions must follow the order in config/rating.json")

    increment = Decimal(str(rubric["scale"]["dimension_increment"]))
    minimum = Decimal(str(rubric["scale"]["minimum"]))
    maximum = Decimal(str(rubric["scale"]["maximum"]))
    scores_are_valid = True
    for item in dimensions:
        if not isinstance(item, dict) or isinstance(item.get("score"), bool) \
                or not isinstance(item.get("score"), (int, float)):
            scores_are_valid = False
            continue
        score = Decimal(str(item["score"]))
        if not minimum <= score <= maximum:
            problems.append(f"{item.get('id', 'unknown')} score {score} is outside 0–10")
        if score % increment:
            problems.append(
                f"{item.get('id', 'unknown')} score {score} is not in {increment}-point increments"
            )
        if require_complete:
            rationale = item.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip() or "TODO" in rationale:
                problems.append(f"{item.get('id', 'unknown')} rationale is incomplete")
            if not isinstance(item.get("source_ids"), list) or not item["source_ids"]:
                problems.append(f"{item.get('id', 'unknown')} has no supporting sources")

    if check_total and not missing and not extra and len(actual) == len(configured) \
            and scores_are_valid:
        expected = calculate_rating(rating, rubric)
        if rating.get("score") != expected:
            problems.append(f"stored score {rating.get('score')} does not equal calculated {expected}")

    return problems


def rubric_errors(rubric: dict) -> list[str]:
    """Check cross-field invariants in the configured rubric."""
    problems: list[str] = []
    dimensions = rubric.get("dimensions", [])
    ids = [item.get("id") for item in dimensions]
    if len(ids) != len(set(ids)):
        problems.append("dimension ids are not unique")
    weight = sum(Decimal(str(item.get("weight", 0))) for item in dimensions)
    if weight != Decimal("1"):
        problems.append(f"dimension weights total {weight}, not 1")
    bands = rubric.get("score_bands", [])
    if bands and (bands[0].get("minimum") != 0 or bands[-1].get("maximum") != 10):
        problems.append("score bands must span 0 through 10")
    return problems


def score_band(score: float, rubric: dict) -> str:
    """Return the configured reader-facing label for a score."""
    for band in rubric["score_bands"]:
        if band["minimum"] <= score <= band["maximum"]:
            return band["label"]
    raise ValueError(f"score is outside configured bands: {score}")
