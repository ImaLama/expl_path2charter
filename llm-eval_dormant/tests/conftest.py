"""Shared fixtures for llm-eval tests."""

import pytest

from llm_eval.types import (
    GenerationResult,
    IndividualScore,
    Prompt,
    ProviderConfig,
    Rubric,
    ScoreCriterion,
)


@pytest.fixture
def sample_provider():
    return ProviderConfig(
        key="test-provider",
        name="Test Provider",
        model="test-model",
        tier="free",
        base_url="https://api.test.com/v1",
        env_key="TEST_API_KEY",
    )


@pytest.fixture
def sample_prompt():
    return Prompt(
        key="test-prompt",
        label="Test prompt",
        content="Explain recursion in 3 sentences.",
        difficulty="easy",
    )


@pytest.fixture
def sample_rubric():
    return Rubric(
        criteria=[
            ScoreCriterion(key="accuracy", label="Accuracy",
                           description="Is it correct?", weight=0.5),
            ScoreCriterion(key="clarity", label="Clarity",
                           description="Is it clear?", weight=0.5),
        ],
        judge_preamble="You are an expert evaluator.",
        output_schema={
            "type": "object",
            "properties": {
                "accuracy": {"type": "object"},
                "clarity": {"type": "object"},
            },
        },
    )


@pytest.fixture
def sample_result():
    return GenerationResult(
        provider="test-provider",
        model="test-model",
        name="Test Provider",
        tier="free",
        prompt_key="test-prompt",
        prompt_label="Test prompt",
        content="Recursion is when a function calls itself.",
        elapsed_s=1.5,
        input_tokens=10,
        output_tokens=20,
    )


@pytest.fixture
def sample_score():
    return IndividualScore(
        provider="test-provider",
        model="test-model",
        name="Test Provider",
        prompt_key="test-prompt",
        scores={
            "accuracy": {"score": 4, "issues": []},
            "clarity": {"score": 5, "notes": "Very clear"},
        },
        weighted_total=4.5,
        elapsed_s=1.5,
        output_tokens=20,
    )
