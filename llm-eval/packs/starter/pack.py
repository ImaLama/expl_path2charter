"""
Starter Challenge Pack — generic knowledge prompts for framework testing.

This pack has no domain-specific logic. It exists to verify that the entire
pipeline (generate, score, compare, report) works end-to-end.
"""

from llm_eval.types import ChallengePack, Prompt, Rubric, ScoreCriterion, AutoScorer


class StarterPack(ChallengePack):

    @property
    def name(self) -> str:
        return "starter"

    @property
    def description(self) -> str:
        return "Generic knowledge prompts for framework testing"

    def get_system_prompt(self) -> str | None:
        return "You are a helpful assistant. Answer precisely and completely."

    def get_prompts(self) -> list[Prompt]:
        return [
            Prompt(
                key="easy-recursion",
                label="Explain recursion (easy)",
                content="Explain the concept of recursion in 3 sentences.",
                difficulty="easy",
            ),
            Prompt(
                key="easy-stack-queue",
                label="Stack vs queue (easy)",
                content="What is the difference between a stack and a queue? Give a real-world analogy for each.",
                difficulty="easy",
            ),
            Prompt(
                key="medium-dining-philosophers",
                label="Dining philosophers (medium)",
                content=(
                    "Compare three approaches to solving the dining philosophers "
                    "problem. Include pseudocode for each approach and analyze their "
                    "trade-offs in terms of deadlock prevention, starvation, and performance."
                ),
                difficulty="medium",
            ),
            Prompt(
                key="hard-branch-predictor",
                label="CPU branch prediction (hard)",
                content=(
                    "Explain how a modern CPU branch predictor works, covering "
                    "static prediction, dynamic prediction with BHT, and the performance "
                    "implications of branch misprediction in pipelined architectures."
                ),
                difficulty="hard",
            ),
        ]

    def get_rubric(self) -> Rubric:
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
        return None

    def get_auto_score_weight(self) -> float:
        return 0.0


def get_pack() -> ChallengePack:
    return StarterPack()
