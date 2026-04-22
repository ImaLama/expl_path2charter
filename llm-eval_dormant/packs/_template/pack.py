# packs/_template/pack.py
"""
Template Challenge Pack — copy this to create your own.

Usage:
    python cli.py new-pack my_domain
    # then edit packs/my_domain/pack.py

Each pack must define a class that subclasses ChallengePack and export
a get_pack() function at module level.
"""

from llm_eval.types import ChallengePack, Prompt, Rubric, ScoreCriterion, AutoScorer


class TemplateChallengePack(ChallengePack):
    """Replace this with your domain-specific pack."""

    @property
    def name(self) -> str:
        return "template"

    @property
    def description(self) -> str:
        return "A template challenge pack — copy and customize"

    def get_system_prompt(self) -> str | None:
        """Optional system prompt prepended to all prompts.
        Return None to send just the prompt content with no system message."""
        return "You are a helpful assistant. Answer precisely and completely."

    def get_prompts(self) -> list[Prompt]:
        """Define your prompts here. Include a range of difficulties."""
        return [
            Prompt(
                key="easy-example",
                label="Easy example prompt",
                content="Explain the concept of recursion in 3 sentences.",
                difficulty="easy",
                metadata={},  # pack-specific data (e.g. test cases for coding packs)
            ),
            Prompt(
                key="hard-example",
                label="Hard example prompt",
                content=(
                    "Compare and contrast three different approaches to "
                    "solving the dining philosophers problem. Include "
                    "pseudocode for each approach and analyze their "
                    "trade-offs in terms of deadlock prevention, "
                    "starvation, and performance."
                ),
                difficulty="hard",
                metadata={},
            ),
        ]

    def get_rubric(self) -> Rubric:
        """Define scoring criteria. Weights must sum to 1.0."""
        return Rubric(
            criteria=[
                ScoreCriterion(
                    key="accuracy",
                    label="Accuracy",
                    description=(
                        "Is the information factually correct? Are there any "
                        "errors, hallucinations, or misleading statements? "
                        "Score 1 = major errors. Score 5 = fully accurate."
                    ),
                    weight=0.40,
                ),
                ScoreCriterion(
                    key="completeness",
                    label="Completeness",
                    description=(
                        "Does the response address all parts of the prompt? "
                        "Are there missing elements or unanswered aspects? "
                        "Score 1 = major gaps. Score 5 = fully complete."
                    ),
                    weight=0.35,
                ),
                ScoreCriterion(
                    key="clarity",
                    label="Clarity & Presentation",
                    description=(
                        "Is the response well-organized, clearly written, "
                        "and easy to follow? Is the formatting helpful? "
                        "Score 1 = confusing mess. Score 5 = crystal clear."
                    ),
                    weight=0.25,
                ),
            ],
            judge_preamble=(
                "You are an expert evaluator. Score the following response "
                "against the original prompt using the rubric provided."
            ),
            output_schema={
                "type": "object",
                "properties": {
                    "accuracy": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "issues": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "completeness": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "missing": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "clarity": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "overall_notes": {"type": "string"},
                },
            },
        )

    def get_auto_scorer(self) -> AutoScorer | None:
        """Return None for pure LLM-judged packs.
        For automated scoring (e.g. code execution), return an AutoScorer instance.
        See packs/coding/pack.py for an example."""
        return None

    def get_auto_score_weight(self) -> float:
        """Weight of auto-scorer in final score (0.0 to 1.0).
        Only meaningful if get_auto_scorer() returns something.
        E.g. 0.5 means 50% auto-scored, 50% LLM-judged."""
        return 0.0


def get_pack() -> ChallengePack:
    """Entry point — the framework calls this to get the pack instance."""
    return TemplateChallengePack()
