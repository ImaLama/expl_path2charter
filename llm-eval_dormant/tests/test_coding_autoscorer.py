"""Tests for the coding pack's AutoScorer — code extraction, sandboxed execution, scoring."""

import pytest

from llm_eval.types import GenerationResult, Prompt


def _get_autoscorer():
    from packs.coding.pack import CodingAutoScorer
    return CodingAutoScorer()


def _make_result(content: str) -> GenerationResult:
    return GenerationResult(
        provider="test", model="m", name="Test", tier="t",
        prompt_key="test", prompt_label="Test",
        content=content, elapsed_s=1.0,
    )


def _make_prompt(function_name: str, test_cases: list[dict]) -> Prompt:
    return Prompt(
        key="test", label="Test", content="Test prompt",
        difficulty="easy",
        metadata={"function_name": function_name, "test_cases": test_cases},
    )


class TestCodeExtraction:
    def test_extracts_python_fenced_code(self):
        scorer = _get_autoscorer()
        content = 'Some text\n```python\ndef foo():\n    return 42\n```\nMore text'
        code = scorer._extract_code(content)
        assert code is not None
        assert "def foo" in code

    def test_extracts_py_fenced_code(self):
        scorer = _get_autoscorer()
        content = '```py\nx = 1\n```'
        code = scorer._extract_code(content)
        assert code is not None
        assert "x = 1" in code

    def test_extracts_bare_fenced_code(self):
        scorer = _get_autoscorer()
        content = '```\nprint("hello")\n```'
        code = scorer._extract_code(content)
        assert code is not None
        assert 'print("hello")' in code

    def test_returns_none_for_no_code(self):
        scorer = _get_autoscorer()
        code = scorer._extract_code("Just plain text with no code blocks")
        assert code is None

    def test_extracts_first_code_block(self):
        scorer = _get_autoscorer()
        content = '```python\nfirst = 1\n```\n\n```python\nsecond = 2\n```'
        code = scorer._extract_code(content)
        assert "first = 1" in code


class TestSandboxedExecution:
    def test_runs_valid_python(self):
        scorer = _get_autoscorer()
        result = scorer._run_sandboxed("print('hello')")
        assert result["error"] is None
        assert "hello" in result["stdout"]

    def test_catches_syntax_error(self):
        scorer = _get_autoscorer()
        result = scorer._run_sandboxed("def broken(:\n    pass")
        assert result["error"] is not None

    def test_catches_runtime_error(self):
        scorer = _get_autoscorer()
        result = scorer._run_sandboxed("raise ValueError('boom')")
        assert result["error"] is not None

    def test_timeout_handling(self):
        scorer = _get_autoscorer()
        result = scorer._run_sandboxed("import time; time.sleep(30)")
        assert result["error"] is not None
        assert "Timeout" in result["error"]


class TestScoring:
    def test_all_tests_pass(self):
        scorer = _get_autoscorer()
        prompt = _make_prompt("reverse_words", [
            {"input": "hello world", "expected": "world hello"},
            {"input": "a", "expected": "a"},
        ])
        result = _make_result(
            '```python\ndef reverse_words(s):\n    return " ".join(s.split()[::-1])\n```'
        )
        scores = scorer.score(prompt, result)
        assert scores["executes"]["score"] == 5
        assert scores["correctness"]["score"] == 5

    def test_some_tests_fail(self):
        scorer = _get_autoscorer()
        prompt = _make_prompt("add", [
            {"input": 1, "expected": 2},
            {"input": 5, "expected": 6},
            {"input": 0, "expected": 1},
        ])
        # This function always returns input + 2, so first test fails
        result = _make_result(
            '```python\ndef add(x):\n    return x + 2\n```'
        )
        scores = scorer.score(prompt, result)
        assert scores["executes"]["score"] == 5  # runs without error
        assert scores["correctness"]["score"] < 5  # not all pass

    def test_no_code_block(self):
        scorer = _get_autoscorer()
        prompt = _make_prompt("foo", [{"input": 1, "expected": 2}])
        result = _make_result("I think the answer is to use a loop.")
        scores = scorer.score(prompt, result)
        assert scores["executes"]["score"] == 1
        assert scores["correctness"]["score"] == 1

    def test_code_that_crashes(self):
        scorer = _get_autoscorer()
        prompt = _make_prompt("broken", [{"input": 1, "expected": 2}])
        result = _make_result(
            '```python\ndef broken(x):\n    raise RuntimeError("nope")\n```'
        )
        scores = scorer.score(prompt, result)
        # Should not crash the framework
        assert scores["executes"]["score"] == 1

    def test_none_input_for_no_args(self):
        scorer = _get_autoscorer()
        prompt = _make_prompt("get_answer", [
            {"input": None, "expected": 42},
        ])
        result = _make_result(
            '```python\ndef get_answer():\n    return 42\n```'
        )
        scores = scorer.score(prompt, result)
        assert scores["executes"]["score"] == 5
        assert scores["correctness"]["score"] == 5
