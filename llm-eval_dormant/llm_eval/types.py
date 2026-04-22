"""
Shared data structures and abstract base classes for the LLM evaluation framework.

All domain-specific logic lives in challenge packs — these types are domain-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Provider & prompt types
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    key: str                    # e.g. "gemini", "ollama-qwen32b"
    name: str                   # human-readable, e.g. "Google Gemini 2.5 Pro"
    model: str                  # model string sent to API
    tier: str                   # "free", "local", "$5 prepaid", etc.
    base_url: str | None = None         # OpenAI-compatible endpoint (None for Anthropic)
    env_key: str | None = None          # env var name for API key (None for Ollama)
    native_sdk: str | None = None       # "anthropic" if it uses its own SDK, else None


@dataclass
class Prompt:
    """A single challenge prompt from a pack."""
    key: str                    # e.g. "goblin-inventor"
    label: str                  # human description
    content: str                # the actual prompt text
    difficulty: str             # "easy", "medium", "hard" (for reporting)
    metadata: dict = field(default_factory=dict)  # pack-specific extra data


# ---------------------------------------------------------------------------
# Generation results
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    """Result of running a prompt against a single provider."""
    provider: str
    model: str
    name: str
    tier: str
    prompt_key: str
    prompt_label: str
    content: str                # the raw model output
    elapsed_s: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None    # None if success


# ---------------------------------------------------------------------------
# Scoring types
# ---------------------------------------------------------------------------

@dataclass
class ScoreCriterion:
    """A single scoring dimension within a rubric."""
    key: str                    # e.g. "rule_legality"
    label: str                  # e.g. "Rule Legality"
    description: str            # what the judge should evaluate
    weight: float               # 0.0 to 1.0, all weights in a rubric must sum to 1.0


@dataclass
class Rubric:
    """Scoring rubric defining how judge evaluates responses."""
    criteria: list[ScoreCriterion]
    judge_preamble: str         # domain context for the judge
    output_schema: dict         # JSON schema the judge should return per criterion

    def __post_init__(self) -> None:
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Rubric weights must sum to 1.0, got {total:.3f}"
            )


@dataclass
class IndividualScore:
    """Scored result for one provider on one prompt."""
    provider: str
    model: str
    name: str
    prompt_key: str
    scores: dict                # criterion_key -> {score: int, ...extra fields}
    weighted_total: float       # computed from scores + rubric weights
    auto_scores: dict | None = None   # from automated validator, if any
    elapsed_s: float | None = None
    output_tokens: int | None = None


@dataclass
class HeadToHeadResult:
    """Result of a pairwise comparison between two providers."""
    prompt_key: str
    provider_a: str
    provider_b: str
    round_1_winner: str         # "A", "B", or "tie"
    round_2_winner: str         # reversed order result (mapped back to original)
    final_winner: str           # provider key or "tie"
    consistency: str            # "consistent" or "inconsistent"
    reasoning: str


# ---------------------------------------------------------------------------
# Abstract base classes for challenge packs
# ---------------------------------------------------------------------------

class ChallengePack(ABC):
    """Interface that all challenge packs must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for the pack, e.g. 'starter', 'pf2e'."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the pack."""
        ...

    @abstractmethod
    def get_prompts(self) -> list[Prompt]:
        """Return all prompts in this pack."""
        ...

    @abstractmethod
    def get_rubric(self) -> Rubric:
        """Return the scoring rubric for this pack."""
        ...

    def get_auto_scorer(self) -> AutoScorer | None:
        """Return an AutoScorer if this pack supports automated scoring."""
        return None

    def get_system_prompt(self) -> str | None:
        """Optional system prompt prepended to all prompts."""
        return None

    def get_auto_score_weight(self) -> float:
        """Weight of auto-scorer in final score (0.0 to 1.0). Default 0."""
        return 0.0


class AutoScorer(ABC):
    """Interface for automated scoring (e.g. code execution)."""

    @abstractmethod
    def score(self, prompt: Prompt, result: GenerationResult) -> dict:
        """Score a generation result.

        Returns {criterion_key: {score: int, details: str}}.
        """
        ...
