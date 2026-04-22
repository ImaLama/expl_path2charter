"""Tests for llm_eval/report.py — report generation with sample data."""

import json
from pathlib import Path

import pytest

from llm_eval.report import generate_report
from llm_eval.types import HeadToHeadResult, IndividualScore


class TestGenerateReport:
    def test_generates_markdown_file(self, tmp_path):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        scores = [
            IndividualScore(
                provider="alpha", model="m1", name="Alpha Model",
                prompt_key="easy-recursion",
                scores={"accuracy": {"score": 5}, "completeness": {"score": 4}, "clarity": {"score": 4}},
                weighted_total=4.35, elapsed_s=1.5, output_tokens=50,
            ),
            IndividualScore(
                provider="beta", model="m2", name="Beta Model",
                prompt_key="easy-recursion",
                scores={"accuracy": {"score": 3}, "completeness": {"score": 3}, "clarity": {"score": 4}},
                weighted_total=3.25, elapsed_s=2.0, output_tokens=80,
            ),
        ]

        report_path = generate_report(scores, None, pack, "gemini", tmp_path)
        assert report_path.exists()
        assert report_path.suffix == ".md"

        content = report_path.read_text()
        assert "Alpha Model" in content
        assert "Beta Model" in content
        assert "4.35" in content

    def test_generates_json_scores(self, tmp_path):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        scores = [
            IndividualScore(
                provider="alpha", model="m1", name="Alpha",
                prompt_key="easy-recursion",
                scores={"accuracy": {"score": 5}},
                weighted_total=4.0, elapsed_s=1.0, output_tokens=40,
            ),
        ]

        generate_report(scores, None, pack, "gemini", tmp_path)
        json_files = list(tmp_path.glob("*_scores_*.json"))
        assert len(json_files) == 1

        data = json.loads(json_files[0].read_text())
        assert data["judge"] == "gemini"
        assert data["pack"] == "starter"
        assert len(data["individual_scores"]) == 1

    def test_includes_head_to_head(self, tmp_path):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        scores = [
            IndividualScore(
                provider="alpha", model="m", name="Alpha",
                prompt_key="easy-recursion",
                scores={}, weighted_total=4.0, elapsed_s=1.0, output_tokens=40,
            ),
        ]
        h2h = [
            HeadToHeadResult(
                prompt_key="easy-recursion", provider_a="alpha", provider_b="beta",
                round_1_winner="A", round_2_winner="A",
                final_winner="alpha", consistency="consistent",
                reasoning="Alpha was more thorough",
            ),
        ]

        report_path = generate_report(scores, h2h, pack, "gemini", tmp_path)
        content = report_path.read_text()
        assert "Head-to-Head" in content
        assert "Win Tally" in content
        assert "alpha" in content

    def test_aggregate_rankings(self, tmp_path):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("starter")

        scores = [
            IndividualScore(
                provider="alpha", model="m", name="Alpha",
                prompt_key="easy-recursion",
                scores={}, weighted_total=4.0, elapsed_s=1.0, output_tokens=40,
            ),
            IndividualScore(
                provider="alpha", model="m", name="Alpha",
                prompt_key="easy-stack-queue",
                scores={}, weighted_total=5.0, elapsed_s=0.5, output_tokens=30,
            ),
            IndividualScore(
                provider="beta", model="m", name="Beta",
                prompt_key="easy-recursion",
                scores={}, weighted_total=3.0, elapsed_s=2.0, output_tokens=60,
            ),
        ]

        report_path = generate_report(scores, None, pack, "gemini", tmp_path)
        content = report_path.read_text()
        assert "Aggregate Rankings" in content
        # Alpha should rank higher (avg 4.5 vs 3.0)
        alpha_pos = content.index("Alpha")
        beta_pos = content.index("Beta")
        # In aggregate section, Alpha should appear before Beta
        assert "4.50" in content

    def test_includes_auto_scores(self, tmp_path):
        from llm_eval.discovery import get_pack_by_name
        pack = get_pack_by_name("coding")

        scores = [
            IndividualScore(
                provider="alpha", model="m", name="Alpha",
                prompt_key="string-reversal",
                scores={"code_quality": {"score": 5}},
                weighted_total=4.5, elapsed_s=1.0, output_tokens=40,
                auto_scores={"executes": {"score": 5, "details": "Runs cleanly"},
                             "correctness": {"score": 5, "details": "5/5 passed"}},
            ),
        ]

        report_path = generate_report(scores, None, pack, "gemini", tmp_path)
        content = report_path.read_text()
        assert "Auto-Scores" in content
        assert "Runs cleanly" in content
