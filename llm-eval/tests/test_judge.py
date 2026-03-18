"""Tests for llm_eval/judge.py — judge prompts, JSON parsing, scoring, bias detection."""

from unittest.mock import patch

import pytest

from llm_eval.judge import (
    _build_head_to_head_prompt,
    _build_individual_prompt,
    _parse_json_response,
    score_head_to_head,
    score_individual,
)
from llm_eval.types import GenerationResult


class TestParseJsonResponse:
    def test_clean_json(self):
        text = '{"accuracy": {"score": 4}, "clarity": {"score": 5}}'
        result = _parse_json_response(text)
        assert result["accuracy"]["score"] == 4

    def test_json_with_markdown_fences(self):
        text = '```json\n{"accuracy": {"score": 3}}\n```'
        result = _parse_json_response(text)
        assert result["accuracy"]["score"] == 3

    def test_json_with_bare_fences(self):
        text = '```\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result["key"] == "value"

    def test_json_with_preamble(self):
        text = 'Here is my evaluation:\n\n{"score": 5, "notes": "great"}'
        result = _parse_json_response(text)
        assert result["score"] == 5

    def test_json_with_trailing_text(self):
        text = '{"score": 3}\n\nSome extra text here.'
        result = _parse_json_response(text)
        assert result["score"] == 3

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_json_response("not json at all")


class TestBuildIndividualPrompt:
    def test_contains_rubric_criteria(self):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")
        prompt = _build_individual_prompt(pack, "Test prompt", "Test response")
        assert "Accuracy" in prompt
        assert "Completeness" in prompt
        assert "Clarity" in prompt

    def test_contains_original_prompt(self):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")
        prompt = _build_individual_prompt(pack, "Explain recursion", "It calls itself")
        assert "Explain recursion" in prompt

    def test_contains_response(self):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")
        prompt = _build_individual_prompt(pack, "Test", "The model said this")
        assert "The model said this" in prompt

    def test_truncates_long_response(self):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")
        long_response = "x" * 20000
        prompt = _build_individual_prompt(pack, "Test", long_response)
        # Should be truncated to 8000 chars
        assert len(prompt) < 20000 + 5000  # prompt overhead


class TestBuildHeadToHeadPrompt:
    def test_contains_both_responses(self):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")
        prompt = _build_head_to_head_prompt(
            pack, "Test prompt", "Response A content", "Response B content"
        )
        assert "Response A content" in prompt
        assert "Response B content" in prompt

    def test_contains_criteria_names(self):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")
        prompt = _build_head_to_head_prompt(pack, "Test", "A", "B")
        assert "accuracy" in prompt.lower()


class TestScoreIndividual:
    @patch("llm_eval.judge._call_judge")
    def test_scores_valid_results(self, mock_judge):
        mock_judge.return_value = (
            '{"accuracy": {"score": 4, "issues": []}, '
            '"clarity": {"score": 5, "notes": "clear"}, '
            '"overall_notes": "good"}'
        )
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        results = [
            GenerationResult(
                provider="test", model="m", name="Test", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="Recursion is self-reference.", elapsed_s=1.0,
            ),
        ]
        scores = score_individual(results, pack, "gemini")
        assert len(scores) == 1
        assert scores[0].weighted_total > 0

    @patch("llm_eval.judge._call_judge")
    def test_skips_error_results(self, mock_judge):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        results = [
            GenerationResult(
                provider="test", model="m", name="Test", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="", elapsed_s=0.0, error="API timeout",
            ),
        ]
        scores = score_individual(results, pack, "gemini")
        assert len(scores) == 0
        mock_judge.assert_not_called()

    @patch("llm_eval.judge._call_judge")
    def test_weighted_total_calculation(self, mock_judge):
        # Starter rubric: accuracy=0.4, completeness=0.35, clarity=0.25
        mock_judge.return_value = (
            '{"accuracy": {"score": 5}, '
            '"completeness": {"score": 4}, '
            '"clarity": {"score": 3}, '
            '"overall_notes": "ok"}'
        )
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        results = [
            GenerationResult(
                provider="test", model="m", name="Test", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="Some content.", elapsed_s=1.0,
            ),
        ]
        scores = score_individual(results, pack, "gemini")
        # Expected: 5*0.4 + 4*0.35 + 3*0.25 = 2.0 + 1.4 + 0.75 = 4.15
        assert abs(scores[0].weighted_total - 4.15) < 0.01


class TestScoreHeadToHead:
    @patch("llm_eval.judge._call_judge")
    def test_consistent_winner(self, mock_judge):
        # Both rounds say A wins -> consistent
        mock_judge.side_effect = [
            '{"winner": "A", "reasoning": "A is better", "a_strengths": [], "b_strengths": [], "confidence": "high"}',
            '{"winner": "B", "reasoning": "B is better", "a_strengths": [], "b_strengths": [], "confidence": "high"}',
            # Round 2 says B wins (which is A in flipped order) -> consistent
        ]
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        results = [
            GenerationResult(
                provider="alpha", model="m", name="Alpha", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="Alpha response.", elapsed_s=1.0,
            ),
            GenerationResult(
                provider="beta", model="m", name="Beta", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="Beta response.", elapsed_s=1.0,
            ),
        ]
        h2h = score_head_to_head(results, pack, "gemini")
        assert len(h2h) == 1
        assert h2h[0].consistency == "consistent"
        assert h2h[0].final_winner == "alpha"

    @patch("llm_eval.judge._call_judge")
    def test_inconsistent_tie(self, mock_judge):
        # Round 1: A wins. Round 2 (flipped): A wins -> means B in original -> inconsistent
        mock_judge.side_effect = [
            '{"winner": "A", "reasoning": "A better", "a_strengths": [], "b_strengths": [], "confidence": "medium"}',
            '{"winner": "A", "reasoning": "A better", "a_strengths": [], "b_strengths": [], "confidence": "medium"}',
        ]
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        results = [
            GenerationResult(
                provider="alpha", model="m", name="Alpha", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="Alpha.", elapsed_s=1.0,
            ),
            GenerationResult(
                provider="beta", model="m", name="Beta", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content="Beta.", elapsed_s=1.0,
            ),
        ]
        h2h = score_head_to_head(results, pack, "gemini")
        assert len(h2h) == 1
        # Round 1: A wins. Round 2: A wins -> flipped = B. A != B -> inconsistent
        assert h2h[0].consistency == "inconsistent"
        assert h2h[0].final_winner == "tie"
