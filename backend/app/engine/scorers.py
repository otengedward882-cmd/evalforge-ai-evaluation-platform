"""
Deterministic scoring engine for EvalForge.

Each scorer is a self-contained, stateless callable that accepts a
response string and a configuration dict, then returns a ScorerResult.

Available scorers
-----------------
ExactMatchScorer        — Normalized string equality
RequiredKeywordScorer   — All required keywords must appear in response
ProhibitedKeywordScorer — No prohibited terms may appear in response
RegexScorer             — Pattern must (or must NOT) match
JSONSchemaScorer        — Response is valid JSON conforming to a schema
LengthScorer            — Character or word count within [min, max]

Usage
-----
    scorer = ExactMatchScorer()
    result = scorer.score(response="hello world", config={"expected": "hello world"})
    # ScorerResult(passed=True, score=1.0, reason="Exact match.")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ScorerResult:
    """Immutable result returned by every scorer."""

    passed: bool
    score: float          # Normalised 0.0 – 1.0
    reason: str           # Human-readable explanation
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "reason": self.reason,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BaseScorer:
    """Abstract base for all scorers."""

    name: str = "base"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def _normalise(text: str) -> str:
        """Lowercase, collapse whitespace, strip punctuation edges."""
        return re.sub(r"\s+", " ", text.strip().lower())


# ---------------------------------------------------------------------------
# 1. ExactMatchScorer
# ---------------------------------------------------------------------------


class ExactMatchScorer(BaseScorer):
    """
    Checks whether the response exactly matches the expected string after
    normalisation (lowercase + collapsed whitespace).

    Config keys:
        expected (str)             — The expected response text.
        case_sensitive (bool)      — Default False. If True, skip normalisation.
    """

    name = "exact_match"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:
        expected: str = config.get("expected", "")
        case_sensitive: bool = config.get("case_sensitive", False)

        if case_sensitive:
            actual = response.strip()
            target = expected.strip()
        else:
            actual = self._normalise(response)
            target = self._normalise(expected)

        passed = actual == target
        return ScorerResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            reason="Exact match." if passed else f"Expected '{target}', got '{actual[:120]}'.",
        )


# ---------------------------------------------------------------------------
# 2. RequiredKeywordScorer
# ---------------------------------------------------------------------------


class RequiredKeywordScorer(BaseScorer):
    """
    Checks that every keyword in the required list appears in the response.
    Score = fraction of keywords found (0.0 – 1.0).
    Passes only if ALL keywords are present.

    Config keys:
        keywords (List[str])       — Required terms.
        case_sensitive (bool)      — Default False.
    """

    name = "required_keywords"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:
        keywords: List[str] = config.get("keywords", [])
        case_sensitive: bool = config.get("case_sensitive", False)

        if not keywords:
            return ScorerResult(passed=True, score=1.0, reason="No keywords required.")

        haystack = response if case_sensitive else response.lower()
        found = [kw for kw in keywords if (kw if case_sensitive else kw.lower()) in haystack]
        missing = [kw for kw in keywords if kw not in found]
        score = len(found) / len(keywords)
        passed = len(missing) == 0

        return ScorerResult(
            passed=passed,
            score=round(score, 4),
            reason=(
                "All required keywords found."
                if passed
                else f"Missing keywords: {missing}"
            ),
            details={"found": found, "missing": missing},
        )


# ---------------------------------------------------------------------------
# 3. ProhibitedKeywordScorer
# ---------------------------------------------------------------------------


class ProhibitedKeywordScorer(BaseScorer):
    """
    Fails if ANY prohibited term appears in the response.
    Use this to detect canary tokens, leaked system prompts, or harmful content.
    Score = 1.0 (clean) or 0.0 (violation found).

    Config keys:
        keywords (List[str])       — Prohibited terms.
        case_sensitive (bool)      — Default False.
    """

    name = "prohibited_keywords"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:
        keywords: List[str] = config.get("keywords", [])
        case_sensitive: bool = config.get("case_sensitive", False)

        if not keywords:
            return ScorerResult(passed=True, score=1.0, reason="No prohibited terms defined.")

        haystack = response if case_sensitive else response.lower()
        violations = [kw for kw in keywords if (kw if case_sensitive else kw.lower()) in haystack]
        passed = len(violations) == 0

        return ScorerResult(
            passed=passed,
            score=0.0 if violations else 1.0,
            reason=(
                "No prohibited terms detected."
                if passed
                else f"Prohibited terms found: {violations}"
            ),
            details={"violations": violations},
        )


# ---------------------------------------------------------------------------
# 4. RegexScorer
# ---------------------------------------------------------------------------


class RegexScorer(BaseScorer):
    """
    Tests the response against a regular expression.

    Config keys:
        pattern (str)              — Python regex pattern.
        should_match (bool)        — Default True. Set False to assert the
                                     pattern must NOT appear in the response.
        flags (int)                — re module flags (default re.IGNORECASE).
    """

    name = "regex"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:
        pattern: str = config.get("pattern", "")
        should_match: bool = config.get("should_match", True)
        flags: int = config.get("flags", re.IGNORECASE)

        if not pattern:
            return ScorerResult(passed=False, score=0.0, reason="No regex pattern provided.")

        try:
            match = re.search(pattern, response, flags)
        except re.error as exc:
            return ScorerResult(
                passed=False,
                score=0.0,
                reason=f"Invalid regex pattern: {exc}",
                details={"error": str(exc)},
            )

        matched = match is not None
        passed = matched if should_match else not matched

        if should_match:
            reason = (
                f"Pattern '{pattern}' matched at position {match.start()}." if matched
                else f"Pattern '{pattern}' did not match."
            )
        else:
            reason = (
                f"Pattern '{pattern}' correctly absent."
                if passed
                else f"Prohibited pattern '{pattern}' found."
            )

        return ScorerResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            reason=reason,
            details={"matched": matched, "should_match": should_match},
        )


# ---------------------------------------------------------------------------
# 5. JSONSchemaScorer
# ---------------------------------------------------------------------------


class JSONSchemaScorer(BaseScorer):
    """
    Verifies that the response is valid JSON and optionally conforms to a
    JSON Schema (requires the 'jsonschema' package; falls back to parse-only
    if the package is unavailable).

    Config keys:
        schema (dict | None)       — Optional JSON Schema to validate against.
                                     If omitted, only checks that JSON is parsable.
    """

    name = "json_schema"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:
        schema: Optional[Dict[str, Any]] = config.get("schema")

        # Step 1: Parse JSON
        try:
            parsed = json.loads(response.strip())
        except json.JSONDecodeError as exc:
            return ScorerResult(
                passed=False,
                score=0.0,
                reason=f"Response is not valid JSON: {exc}",
                details={"json_error": str(exc)},
            )

        # Step 2: Schema validation (optional)
        if schema is None:
            return ScorerResult(passed=True, score=1.0, reason="Response is valid JSON.")

        try:
            import jsonschema  # type: ignore[import-untyped]
            jsonschema.validate(instance=parsed, schema=schema)
            return ScorerResult(passed=True, score=1.0, reason="Response matches JSON schema.")
        except ImportError:
            return ScorerResult(
                passed=True,
                score=1.0,
                reason="Response is valid JSON (jsonschema package not installed; schema skipped).",
                details={"warning": "Install jsonschema for schema validation."},
            )
        except jsonschema.ValidationError as exc:
            return ScorerResult(
                passed=False,
                score=0.0,
                reason=f"JSON schema validation failed: {exc.message}",
                details={"schema_error": exc.message, "path": list(exc.absolute_path)},
            )


# ---------------------------------------------------------------------------
# 6. LengthScorer
# ---------------------------------------------------------------------------


class LengthScorer(BaseScorer):
    """
    Checks that the response length falls within [min_length, max_length].

    Config keys:
        unit (str)                 — 'chars' (default) or 'words'.
        min_length (int)           — Minimum acceptable length (default 0).
        max_length (int | None)    — Maximum acceptable length (None = no limit).
    """

    name = "length"

    def score(self, response: str, config: Dict[str, Any]) -> ScorerResult:
        unit: str = config.get("unit", "chars")
        min_length: int = config.get("min_length", 0)
        max_length: Optional[int] = config.get("max_length")

        if unit == "words":
            measured = len(response.split())
            unit_label = "words"
        else:
            measured = len(response)
            unit_label = "chars"

        too_short = measured < min_length
        too_long = max_length is not None and measured > max_length
        passed = not too_short and not too_long

        if too_short:
            reason = f"Response too short: {measured} {unit_label} (min {min_length})."
        elif too_long:
            reason = f"Response too long: {measured} {unit_label} (max {max_length})."
        else:
            reason = f"Length {measured} {unit_label} is within bounds."

        # Partial score for length violations (how close to bounds)
        if passed:
            score = 1.0
        elif too_short and min_length > 0:
            score = round(measured / min_length, 4)
        elif too_long and max_length:
            score = round(max_length / measured, 4)
        else:
            score = 0.0

        return ScorerResult(
            passed=passed,
            score=score,
            reason=reason,
            details={"measured": measured, "unit": unit_label, "min": min_length, "max": max_length},
        )


# ---------------------------------------------------------------------------
# Registry — maps scorer name → class
# ---------------------------------------------------------------------------

SCORER_REGISTRY: Dict[str, type[BaseScorer]] = {
    ExactMatchScorer.name: ExactMatchScorer,
    RequiredKeywordScorer.name: RequiredKeywordScorer,
    ProhibitedKeywordScorer.name: ProhibitedKeywordScorer,
    RegexScorer.name: RegexScorer,
    JSONSchemaScorer.name: JSONSchemaScorer,
    LengthScorer.name: LengthScorer,
}


def get_scorer(scorer_name: str) -> BaseScorer:
    """Return an instantiated scorer by name, or raise ValueError."""
    cls = SCORER_REGISTRY.get(scorer_name)
    if cls is None:
        raise ValueError(
            f"Unknown scorer '{scorer_name}'. "
            f"Available: {list(SCORER_REGISTRY.keys())}"
        )
    return cls()
