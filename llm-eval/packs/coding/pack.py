"""
Coding Challenge Pack — programming challenges with automated test execution.

50% LLM-judged (code quality, approach, edge cases, explanation)
50% Auto-scored (execution, correctness, performance)
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from llm_eval.types import (
    AutoScorer,
    ChallengePack,
    GenerationResult,
    Prompt,
    Rubric,
    ScoreCriterion,
)


class CodingAutoScorer(AutoScorer):
    """Extracts code from responses, runs against test cases in a sandbox."""

    def score(self, prompt: Prompt, result: GenerationResult) -> dict:
        test_cases = prompt.metadata.get("test_cases", [])
        function_name = prompt.metadata.get("function_name", "solution")

        # Extract code from response
        code = self._extract_code(result.content)
        if not code:
            return {
                "executes": {"score": 1, "details": "No code block found in response"},
                "correctness": {"score": 1, "details": "No code to test"},
            }

        # Build test script
        test_script = self._build_test_script(code, test_cases, function_name)

        # Run in sandbox
        try:
            exec_result = self._run_sandboxed(test_script)
        except Exception as e:
            return {
                "executes": {"score": 1, "details": f"Execution error: {e}"},
                "correctness": {"score": 1, "details": "Could not execute"},
            }

        # Parse results
        if exec_result["error"]:
            return {
                "executes": {"score": 1, "details": f"Runtime error: {exec_result['error'][:200]}"},
                "correctness": {"score": 1, "details": "Code failed to run"},
            }

        # Parse test results from stdout
        return self._parse_test_results(exec_result["stdout"], len(test_cases))

    def _extract_code(self, content: str) -> str | None:
        """Extract Python code from markdown code fences."""
        # Try python-specific fences first
        patterns = [
            r"```python\s*\n(.*?)```",
            r"```py\s*\n(.*?)```",
            r"```\s*\n(.*?)```",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                return match.group(1).strip()
        return None

    def _build_test_script(
        self, code: str, test_cases: list[dict], function_name: str
    ) -> str:
        """Build a test script that runs the extracted code against test cases."""
        test_lines = []
        for i, tc in enumerate(test_cases):
            inp = repr(tc["input"])
            expected = repr(tc["expected"])
            # Avoid f-string quote conflicts by using separate variables
            call = f"{function_name}()" if tc["input"] is None else f"{function_name}(_inp_{i})"
            inp_line = "" if tc["input"] is None else f"    _inp_{i} = {inp}\n"
            test_lines.append(
                f"try:\n"
                f"{inp_line}"
                f"    _exp_{i} = {expected}\n"
                f"    _res_{i} = {call}\n"
                f"    if _res_{i} == _exp_{i}:\n"
                f"        print('PASS {i}')\n"
                f"    else:\n"
                f"        print('FAIL {i}: got ' + repr(_res_{i}) + ', expected ' + repr(_exp_{i}))\n"
                f"except Exception as e:\n"
                f"    print('ERROR {i}: ' + str(e))"
            )

        return f"{code}\n\n" + "\n".join(test_lines)

    def _run_sandboxed(self, script: str) -> dict:
        """Run a script in a sandboxed subprocess with timeout."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(script)
            f.flush()
            tmp_path = f.name

        try:
            result = subprocess.run(
                ["python", tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return {
                "stdout": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "error": "Timeout (10s)"}
        except Exception as e:
            return {"stdout": "", "error": str(e)}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _parse_test_results(self, stdout: str, total_tests: int) -> dict:
        """Parse PASS/FAIL/ERROR lines from test output."""
        lines = stdout.strip().split("\n") if stdout.strip() else []
        passed = sum(1 for line in lines if line.startswith("PASS"))
        failed = sum(1 for line in lines if line.startswith("FAIL"))
        errors = sum(1 for line in lines if line.startswith("ERROR"))

        # Executes: binary — did the code run at all?
        executes_score = 5 if errors == 0 and (passed + failed) > 0 else 1

        # Correctness: percentage of tests passing, scaled 1-5
        if total_tests > 0 and (passed + failed + errors) > 0:
            pct = passed / total_tests
            correctness_score = max(1, round(1 + pct * 4))
        else:
            correctness_score = 1

        fail_details = [
            line for line in lines if line.startswith(("FAIL", "ERROR"))
        ]
        details_str = "; ".join(fail_details[:5]) if fail_details else "All tests passed"

        return {
            "executes": {
                "score": executes_score,
                "details": f"{'Runs cleanly' if executes_score == 5 else 'Execution errors'}",
            },
            "correctness": {
                "score": correctness_score,
                "details": f"{passed}/{total_tests} passed. {details_str}",
            },
        }


class CodingPack(ChallengePack):

    @property
    def name(self) -> str:
        return "coding"

    @property
    def description(self) -> str:
        return "Programming challenges with automated test execution"

    def get_system_prompt(self) -> str | None:
        return (
            "You are an expert programmer. Solve the given programming challenge "
            "in Python. Provide:\n"
            "1. A clear explanation of your approach and its time/space complexity\n"
            "2. Clean, well-commented code in a Python code block\n"
            "3. Discussion of edge cases you considered"
        )

    def get_prompts(self) -> list[Prompt]:
        return [
            Prompt(
                key="string-reversal",
                label="Reverse words in a string (easy)",
                difficulty="easy",
                content=(
                    "Write a function `reverse_words(s: str) -> str` that reverses "
                    "the order of words in a string. Words are separated by spaces. "
                    "Leading/trailing spaces should be removed, and multiple spaces "
                    "between words should be reduced to a single space.\n\n"
                    "Examples:\n"
                    '  reverse_words("hello world") -> "world hello"\n'
                    '  reverse_words("  the sky is blue  ") -> "blue is sky the"\n'
                    '  reverse_words("a") -> "a"'
                ),
                metadata={
                    "function_name": "reverse_words",
                    "test_cases": [
                        {"input": "hello world", "expected": "world hello"},
                        {"input": "  the sky is blue  ", "expected": "blue is sky the"},
                        {"input": "a", "expected": "a"},
                        {"input": "  spaces   everywhere  ", "expected": "everywhere spaces"},
                        {"input": "", "expected": ""},
                    ],
                },
            ),
            Prompt(
                key="fizzbuzz-variant",
                label="FizzBuzz variant (easy)",
                difficulty="easy",
                content=(
                    "Write a function `fizzbuzz(n: int) -> list[str]` that returns a list "
                    "of strings from 1 to n where:\n"
                    '- Multiples of 3 are replaced with "Fizz"\n'
                    '- Multiples of 5 are replaced with "Buzz"\n'
                    '- Multiples of both 3 and 5 are replaced with "FizzBuzz"\n'
                    "- All other numbers are converted to their string representation\n\n"
                    "Example: fizzbuzz(5) -> ['1', '2', 'Fizz', '4', 'Buzz']"
                ),
                metadata={
                    "function_name": "fizzbuzz",
                    "test_cases": [
                        {"input": 5, "expected": ["1", "2", "Fizz", "4", "Buzz"]},
                        {"input": 1, "expected": ["1"]},
                        {"input": 15, "expected": [
                            "1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8",
                            "Fizz", "Buzz", "11", "Fizz", "13", "14", "FizzBuzz",
                        ]},
                    ],
                },
            ),
            Prompt(
                key="lru-cache",
                label="LRU Cache implementation (medium)",
                difficulty="medium",
                content=(
                    "Implement an LRU (Least Recently Used) cache.\n\n"
                    "Write a class `LRUCache` with:\n"
                    "- `__init__(self, capacity: int)` — initialize with a positive capacity\n"
                    "- `get(self, key: int) -> int` — return the value if key exists, otherwise -1\n"
                    "- `put(self, key: int, value: int) -> None` — insert or update. If at capacity, "
                    "evict the least recently used item first.\n\n"
                    "Both get and put must run in O(1) average time.\n\n"
                    "To test, write a function `test_lru() -> list` that runs this sequence and "
                    "returns the results:\n"
                    "```\n"
                    "cache = LRUCache(2)\n"
                    "cache.put(1, 1)\n"
                    "cache.put(2, 2)\n"
                    "r1 = cache.get(1)       # returns 1\n"
                    "cache.put(3, 3)         # evicts key 2\n"
                    "r2 = cache.get(2)       # returns -1\n"
                    "cache.put(4, 4)         # evicts key 1\n"
                    "r3 = cache.get(1)       # returns -1\n"
                    "r4 = cache.get(3)       # returns 3\n"
                    "r5 = cache.get(4)       # returns 4\n"
                    "return [r1, r2, r3, r4, r5]\n"
                    "```"
                ),
                metadata={
                    "function_name": "test_lru",
                    "test_cases": [
                        {"input": None, "expected": [1, -1, -1, 3, 4]},
                    ],
                },
            ),
            Prompt(
                key="longest-palindrome",
                label="Longest palindromic substring (medium)",
                difficulty="medium",
                content=(
                    "Write a function `longest_palindrome(s: str) -> str` that finds "
                    "the longest palindromic substring in a given string.\n\n"
                    "If there are multiple with the same length, return the first one found.\n\n"
                    "Examples:\n"
                    '  longest_palindrome("babad") -> "bab" (or "aba")\n'
                    '  longest_palindrome("cbbd") -> "bb"\n'
                    '  longest_palindrome("a") -> "a"\n'
                    '  longest_palindrome("racecar") -> "racecar"'
                ),
                metadata={
                    "function_name": "longest_palindrome",
                    "test_cases": [
                        {"input": "cbbd", "expected": "bb"},
                        {"input": "a", "expected": "a"},
                        {"input": "racecar", "expected": "racecar"},
                        {"input": "abcde", "expected": "a"},
                        {"input": "", "expected": ""},
                    ],
                },
            ),
            Prompt(
                key="nqueens",
                label="N-Queens solver (hard)",
                difficulty="hard",
                content=(
                    "Write a function `solve_nqueens(n: int) -> int` that returns the "
                    "number of distinct solutions to the N-Queens puzzle.\n\n"
                    "The N-Queens puzzle is placing N chess queens on an N×N board so "
                    "that no two queens threaten each other (no same row, column, or diagonal).\n\n"
                    "Examples:\n"
                    "  solve_nqueens(1) -> 1\n"
                    "  solve_nqueens(4) -> 2\n"
                    "  solve_nqueens(8) -> 92"
                ),
                metadata={
                    "function_name": "solve_nqueens",
                    "test_cases": [
                        {"input": 1, "expected": 1},
                        {"input": 4, "expected": 2},
                        {"input": 5, "expected": 10},
                        {"input": 8, "expected": 92},
                    ],
                },
            ),
        ]

    def get_rubric(self) -> Rubric:
        return Rubric(
            criteria=[
                ScoreCriterion(
                    key="code_quality",
                    label="Code Quality",
                    description=(
                        "Is the code clean, readable, and idiomatic Python?\n"
                        "- Good variable names, proper formatting\n"
                        "- Appropriate use of Python features and stdlib\n"
                        "- No unnecessary complexity\n"
                        "Score 1 = messy/unreadable. Score 5 = clean, idiomatic."
                    ),
                    weight=0.35,
                ),
                ScoreCriterion(
                    key="approach",
                    label="Algorithm & Approach",
                    description=(
                        "Is the algorithm choice appropriate?\n"
                        "- Efficient time/space complexity for the problem\n"
                        "- Reasoning about why this approach was chosen\n"
                        "- Awareness of alternative approaches\n"
                        "Score 1 = brute force with no reasoning. Score 5 = optimal approach, well-justified."
                    ),
                    weight=0.30,
                ),
                ScoreCriterion(
                    key="edge_cases",
                    label="Edge Case Handling",
                    description=(
                        "Does the solution handle edge cases?\n"
                        "- Empty inputs, single elements, boundary values\n"
                        "- Input validation where appropriate\n"
                        "- Discussion of potential failure modes\n"
                        "Score 1 = ignores edge cases. Score 5 = thorough handling."
                    ),
                    weight=0.20,
                ),
                ScoreCriterion(
                    key="explanation",
                    label="Explanation Quality",
                    description=(
                        "Is the explanation clear and helpful?\n"
                        "- Describes the approach before or after the code\n"
                        "- States time and space complexity\n"
                        "- Readable by another developer\n"
                        "Score 1 = no explanation. Score 5 = clear, complete explanation."
                    ),
                    weight=0.15,
                ),
            ],
            judge_preamble=(
                "You are an expert software engineer reviewing code solutions. "
                "Evaluate the response for code quality, algorithmic approach, "
                "edge case handling, and explanation quality. Do NOT evaluate "
                "whether the code produces correct output — that is tested "
                "automatically. Focus on the quality of the code and explanation."
            ),
            output_schema={
                "type": "object",
                "properties": {
                    "code_quality": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "approach": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "edge_cases": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "explanation": {
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
        return CodingAutoScorer()

    def get_auto_score_weight(self) -> float:
        return 0.5


def get_pack() -> ChallengePack:
    return CodingPack()
