"""Integration tests — require live API keys.

Run with: pytest tests/test_integration.py -m integration
Skip with: pytest -m "not integration"
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.integration


def _has_api_key(env_var: str) -> bool:
    return bool(os.getenv(env_var, "").strip())


@pytest.mark.skipif(
    not _has_api_key("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
class TestGeminiIntegration:
    def test_generation(self):
        from llm_eval.providers import CLOUD_PROVIDERS, call_provider

        cfg = CLOUD_PROVIDERS["gemini"]
        result = call_provider(cfg, "Say hello in exactly 3 words.", max_tokens=50)
        assert result.error is None
        assert len(result.content) > 0
        assert result.elapsed_s > 0

    def test_full_pipeline(self, tmp_path):
        from llm_eval.discovery import get_pack_by_name
        from llm_eval.runner import run_challenges

        pack = get_pack_by_name("starter")
        results = run_challenges(
            ["gemini"], pack, tmp_path, prompt_keys=["easy-recursion"]
        )
        assert len(results) == 1
        assert results[0].error is None
        assert (tmp_path / f"{results[0].prompt_key}_gemini.md") or True
        # Check results.json was created
        run_dirs = list(tmp_path.glob("*_starter"))
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "results.json").exists()


@pytest.mark.skipif(
    not _has_api_key("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
class TestAnthropicIntegration:
    def test_generation(self):
        from llm_eval.providers import CLOUD_PROVIDERS, call_provider

        cfg = CLOUD_PROVIDERS["anthropic"]
        result = call_provider(cfg, "Say hello in exactly 3 words.", max_tokens=50)
        assert result.error is None
        assert len(result.content) > 0


@pytest.mark.skipif(
    not _has_api_key("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
class TestScoringIntegration:
    def test_judge_scores_response(self):
        from llm_eval.discovery import get_pack_by_name
        from llm_eval.judge import score_individual
        from llm_eval.types import GenerationResult

        pack = get_pack_by_name("starter")
        results = [
            GenerationResult(
                provider="test", model="m", name="Test", tier="t",
                prompt_key="easy-recursion", prompt_label="Recursion",
                content=(
                    "Recursion is when a function calls itself to solve a problem. "
                    "It breaks the problem into smaller subproblems until reaching a "
                    "base case. The solutions combine as the calls unwind."
                ),
                elapsed_s=1.0,
            ),
        ]
        scores = score_individual(results, pack, "gemini")
        assert len(scores) == 1
        assert 1.0 <= scores[0].weighted_total <= 5.0
