"""
Unit tests for all six deterministic scorers.

Each scorer is tested with:
  - True positive  (should pass, expected score)
  - True negative  (should fail, expected score)
  - Boundary / edge cases specific to the scorer
"""

import pytest
from app.engine.scorers import (
    ExactMatchScorer,
    JSONSchemaScorer,
    LengthScorer,
    ProhibitedKeywordScorer,
    RegexScorer,
    RequiredKeywordScorer,
    ScorerResult,
    get_scorer,
)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _ok(result: ScorerResult) -> None:
    assert result.passed is True
    assert result.score == 1.0


def _fail(result: ScorerResult) -> None:
    assert result.passed is False


# ---------------------------------------------------------------------------
# ExactMatchScorer
# ---------------------------------------------------------------------------


class TestExactMatchScorer:
    scorer = ExactMatchScorer()

    def test_exact_match_passes(self) -> None:
        result = self.scorer.score("Hello World", {"expected": "Hello World"})
        _ok(result)

    def test_case_insensitive_by_default(self) -> None:
        result = self.scorer.score("HELLO WORLD", {"expected": "hello world"})
        _ok(result)

    def test_whitespace_normalised(self) -> None:
        result = self.scorer.score("  hello   world  ", {"expected": "hello world"})
        _ok(result)

    def test_mismatch_fails(self) -> None:
        result = self.scorer.score("hello earth", {"expected": "hello world"})
        _fail(result)
        assert result.score == 0.0

    def test_case_sensitive_mode(self) -> None:
        result = self.scorer.score("Hello", {"expected": "hello", "case_sensitive": True})
        _fail(result)

    def test_case_sensitive_exact(self) -> None:
        result = self.scorer.score("Hello", {"expected": "Hello", "case_sensitive": True})
        _ok(result)

    def test_empty_response_vs_empty_expected(self) -> None:
        result = self.scorer.score("", {"expected": ""})
        _ok(result)


# ---------------------------------------------------------------------------
# RequiredKeywordScorer
# ---------------------------------------------------------------------------


class TestRequiredKeywordScorer:
    scorer = RequiredKeywordScorer()

    def test_all_keywords_present(self) -> None:
        result = self.scorer.score(
            "The capital of France is Paris.",
            {"keywords": ["france", "paris"]},
        )
        _ok(result)

    def test_missing_keyword_fails(self) -> None:
        result = self.scorer.score(
            "The capital of Germany is Berlin.",
            {"keywords": ["france", "paris"]},
        )
        _fail(result)
        assert result.score == 0.0
        assert "france" in result.details["missing"]
        assert "paris" in result.details["missing"]

    def test_partial_match_gives_partial_score(self) -> None:
        result = self.scorer.score(
            "Paris is a city.",
            {"keywords": ["paris", "france"]},
        )
        _fail(result)
        assert result.score == 0.5
        assert "paris" in result.details["found"]

    def test_empty_keywords_always_passes(self) -> None:
        result = self.scorer.score("anything", {"keywords": []})
        _ok(result)

    def test_case_sensitive_mode(self) -> None:
        result = self.scorer.score(
            "Paris is a city.",
            {"keywords": ["Paris"], "case_sensitive": True},
        )
        _ok(result)
        # Lowercase version should fail in case-sensitive mode
        result2 = self.scorer.score(
            "Paris is a city.",
            {"keywords": ["paris"], "case_sensitive": True},
        )
        _fail(result2)


# ---------------------------------------------------------------------------
# ProhibitedKeywordScorer
# ---------------------------------------------------------------------------


class TestProhibitedKeywordScorer:
    scorer = ProhibitedKeywordScorer()

    def test_no_prohibited_terms_passes(self) -> None:
        result = self.scorer.score("This is a helpful response.", {"keywords": ["harm", "violence"]})
        _ok(result)

    def test_prohibited_term_found_fails(self) -> None:
        result = self.scorer.score(
            "Here is how to cause harm to others.",
            {"keywords": ["harm"]},
        )
        _fail(result)
        assert result.score == 0.0
        assert "harm" in result.details["violations"]

    def test_multiple_violations_detected(self) -> None:
        result = self.scorer.score(
            "This contains harm and violence.",
            {"keywords": ["harm", "violence"]},
        )
        _fail(result)
        assert len(result.details["violations"]) == 2

    def test_empty_keywords_always_passes(self) -> None:
        result = self.scorer.score("anything", {"keywords": []})
        _ok(result)

    def test_case_insensitive_by_default(self) -> None:
        result = self.scorer.score("This contains HARM.", {"keywords": ["harm"]})
        _fail(result)

    def test_case_sensitive_misses_different_case(self) -> None:
        result = self.scorer.score(
            "HARM detected.",
            {"keywords": ["harm"], "case_sensitive": True},
        )
        _ok(result)  # 'harm' (lowercase) not in 'HARM detected.' when case_sensitive=True


# ---------------------------------------------------------------------------
# RegexScorer
# ---------------------------------------------------------------------------


class TestRegexScorer:
    scorer = RegexScorer()

    def test_pattern_matches(self) -> None:
        result = self.scorer.score(
            "My phone is 555-1234.",
            {"pattern": r"\d{3}-\d{4}"},
        )
        _ok(result)

    def test_pattern_does_not_match_fails(self) -> None:
        result = self.scorer.score(
            "No phone here.",
            {"pattern": r"\d{3}-\d{4}"},
        )
        _fail(result)

    def test_should_not_match_passes_when_absent(self) -> None:
        result = self.scorer.score(
            "This is a clean response with no issues.",
            {"pattern": r"bad", "should_match": False},
        )
        _ok(result)

    def test_should_not_match_fails_when_present(self) -> None:
        result = self.scorer.score(
            "This is a bad response from the model.",
            {"pattern": r"bad", "should_match": False},
        )
        _fail(result)

    def test_invalid_regex_returns_failure(self) -> None:
        result = self.scorer.score("test", {"pattern": r"[invalid"})
        _fail(result)
        assert "Invalid regex" in result.reason

    def test_empty_pattern_returns_failure(self) -> None:
        result = self.scorer.score("test", {"pattern": ""})
        _fail(result)

    def test_case_insensitive_by_default(self) -> None:
        result = self.scorer.score("HELLO", {"pattern": r"hello"})
        _ok(result)


# ---------------------------------------------------------------------------
# JSONSchemaScorer
# ---------------------------------------------------------------------------


class TestJSONSchemaScorer:
    scorer = JSONSchemaScorer()

    def test_valid_json_passes_no_schema(self) -> None:
        result = self.scorer.score('{"key": "value"}', {})
        _ok(result)

    def test_invalid_json_fails(self) -> None:
        result = self.scorer.score("not json at all", {})
        _fail(result)
        assert "not valid JSON" in result.reason

    def test_malformed_json_fails(self) -> None:
        result = self.scorer.score('{"key": "value"', {})
        _fail(result)

    def test_json_array_passes(self) -> None:
        result = self.scorer.score("[1, 2, 3]", {})
        _ok(result)

    def test_schema_validation_pass(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name", "age"],
        }
        result = self.scorer.score('{"name": "Alice", "age": 30}', {"schema": schema})
        # Pass regardless of whether jsonschema is installed
        assert result.passed is True

    def test_schema_validation_fail(self) -> None:
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            pytest.skip("jsonschema not installed — schema validation test skipped")

        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name", "age"],
        }
        # Missing 'age' field — should fail schema validation
        result = self.scorer.score('{"name": "Alice"}', {"schema": schema})
        _fail(result)


# ---------------------------------------------------------------------------
# LengthScorer
# ---------------------------------------------------------------------------


class TestLengthScorer:
    scorer = LengthScorer()

    def test_within_char_bounds_passes(self) -> None:
        result = self.scorer.score("Hello", {"unit": "chars", "min_length": 3, "max_length": 10})
        _ok(result)

    def test_too_short_fails(self) -> None:
        result = self.scorer.score("Hi", {"unit": "chars", "min_length": 5})
        _fail(result)
        assert "too short" in result.reason

    def test_too_long_fails(self) -> None:
        result = self.scorer.score("Hello World", {"unit": "chars", "max_length": 5})
        _fail(result)
        assert "too long" in result.reason

    def test_word_count_within_bounds(self) -> None:
        result = self.scorer.score(
            "The quick brown fox",
            {"unit": "words", "min_length": 3, "max_length": 6},
        )
        _ok(result)
        assert result.details["measured"] == 4

    def test_word_count_too_short(self) -> None:
        result = self.scorer.score("Hi", {"unit": "words", "min_length": 5})
        _fail(result)

    def test_no_max_allows_long_response(self) -> None:
        result = self.scorer.score("A" * 10000, {"min_length": 1})
        _ok(result)

    def test_partial_score_on_too_short(self) -> None:
        result = self.scorer.score("Hi", {"unit": "chars", "min_length": 4})
        _fail(result)
        assert 0.0 < result.score < 1.0

    def test_exact_boundary_passes(self) -> None:
        result = self.scorer.score("Hello", {"unit": "chars", "min_length": 5, "max_length": 5})
        _ok(result)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_get_scorer_known(self) -> None:
        s = get_scorer("exact_match")
        assert isinstance(s, ExactMatchScorer)

    def test_get_scorer_all_registered(self) -> None:
        for name in [
            "exact_match",
            "required_keywords",
            "prohibited_keywords",
            "regex",
            "json_schema",
            "length",
        ]:
            s = get_scorer(name)
            assert s is not None

    def test_get_scorer_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown scorer"):
            get_scorer("nonexistent_scorer")
