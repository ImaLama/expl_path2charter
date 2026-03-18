"""Tests for llm_eval/types.py — dataclass construction and validation."""

import pytest

from llm_eval.types import (
    AutoScorer,
    ChallengePack,
    GenerationResult,
    HeadToHeadResult,
    IndividualScore,
    Prompt,
    ProviderConfig,
    Rubric,
    ScoreCriterion,
)


class TestProviderConfig:
    def test_basic_construction(self):
        cfg = ProviderConfig(
            key="gemini", name="Gemini", model="gemini-pro", tier="free"
        )
        assert cfg.key == "gemini"
        assert cfg.base_url is None
        assert cfg.env_key is None
        assert cfg.native_sdk is None

    def test_full_construction(self):
        cfg = ProviderConfig(
            key="anthropic", name="Claude", model="claude-opus-4-6",
            tier="$5", env_key="ANTHROPIC_API_KEY", native_sdk="anthropic",
        )
        assert cfg.native_sdk == "anthropic"
        assert cfg.env_key == "ANTHROPIC_API_KEY"


class TestPrompt:
    def test_basic_construction(self):
        p = Prompt(key="test", label="Test", content="Hello", difficulty="easy")
        assert p.metadata == {}

    def test_with_metadata(self):
        p = Prompt(
            key="code", label="Code", content="Write fizzbuzz",
            difficulty="easy", metadata={"test_cases": [{"input": 5}]},
        )
        assert len(p.metadata["test_cases"]) == 1


class TestGenerationResult:
    def test_success_result(self, sample_result):
        assert sample_result.error is None
        assert sample_result.content != ""

    def test_error_result(self):
        r = GenerationResult(
            provider="test", model="m", name="n", tier="t",
            prompt_key="p", prompt_label="l", content="",
            elapsed_s=0.0, error="Connection timeout",
        )
        assert r.error == "Connection timeout"


class TestRubric:
    def test_valid_weights(self, sample_rubric):
        assert len(sample_rubric.criteria) == 2
        total = sum(c.weight for c in sample_rubric.criteria)
        assert abs(total - 1.0) < 0.01

    def test_invalid_weights_raises(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            Rubric(
                criteria=[
                    ScoreCriterion(key="a", label="A", description="x", weight=0.3),
                    ScoreCriterion(key="b", label="B", description="y", weight=0.3),
                ],
                judge_preamble="test",
                output_schema={},
            )

    def test_single_criterion_valid(self):
        r = Rubric(
            criteria=[
                ScoreCriterion(key="only", label="Only", description="x", weight=1.0),
            ],
            judge_preamble="test",
            output_schema={},
        )
        assert len(r.criteria) == 1

    def test_weights_near_boundary(self):
        # 0.333 + 0.333 + 0.334 = 1.0
        r = Rubric(
            criteria=[
                ScoreCriterion(key="a", label="A", description="x", weight=0.333),
                ScoreCriterion(key="b", label="B", description="y", weight=0.333),
                ScoreCriterion(key="c", label="C", description="z", weight=0.334),
            ],
            judge_preamble="test",
            output_schema={},
        )
        assert len(r.criteria) == 3


class TestIndividualScore:
    def test_construction(self, sample_score):
        assert sample_score.weighted_total == 4.5
        assert sample_score.auto_scores is None

    def test_with_auto_scores(self):
        s = IndividualScore(
            provider="p", model="m", name="n", prompt_key="k",
            scores={"a": {"score": 3}},
            weighted_total=3.5,
            auto_scores={"executes": {"score": 5, "details": "OK"}},
        )
        assert s.auto_scores["executes"]["score"] == 5


class TestHeadToHeadResult:
    def test_consistent(self):
        h = HeadToHeadResult(
            prompt_key="test", provider_a="a", provider_b="b",
            round_1_winner="A", round_2_winner="A",
            final_winner="a", consistency="consistent",
            reasoning="A was better",
        )
        assert h.consistency == "consistent"

    def test_inconsistent(self):
        h = HeadToHeadResult(
            prompt_key="test", provider_a="a", provider_b="b",
            round_1_winner="A", round_2_winner="B",
            final_winner="tie", consistency="inconsistent",
            reasoning="Positional bias",
        )
        assert h.final_winner == "tie"


class TestAbstractClasses:
    def test_challenge_pack_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ChallengePack()

    def test_auto_scorer_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AutoScorer()

    def test_concrete_pack(self):
        class TestPack(ChallengePack):
            @property
            def name(self): return "test"
            @property
            def description(self): return "Test pack"
            def get_prompts(self): return []
            def get_rubric(self):
                return Rubric(
                    criteria=[ScoreCriterion(key="a", label="A", description="x", weight=1.0)],
                    judge_preamble="test", output_schema={},
                )

        pack = TestPack()
        assert pack.name == "test"
        assert pack.get_auto_scorer() is None
        assert pack.get_system_prompt() is None
        assert pack.get_auto_score_weight() == 0.0
