"""Tests for llm_eval/providers.py — provider registry, availability, API calls."""

import os
from unittest.mock import MagicMock, patch

import pytest

from llm_eval.providers import (
    ALL_PROVIDERS,
    CLOUD_PROVIDERS,
    LOCAL_PROVIDERS,
    call_provider,
    get_all_providers,
    list_available,
)
from llm_eval.types import GenerationResult, ProviderConfig


class TestProviderRegistry:
    def test_all_providers_includes_cloud_and_local(self):
        all_p = get_all_providers()
        for key in CLOUD_PROVIDERS:
            assert key in all_p
        for key in LOCAL_PROVIDERS:
            assert key in all_p

    def test_cloud_providers_have_required_fields(self):
        for key, cfg in CLOUD_PROVIDERS.items():
            assert cfg.key == key
            assert cfg.name
            assert cfg.model
            assert cfg.tier
            assert cfg.env_key  # cloud providers need API keys

    def test_local_providers_are_ollama(self):
        for key, cfg in LOCAL_PROVIDERS.items():
            assert key.startswith("ollama-")
            assert cfg.tier == "local"
            assert cfg.env_key is None
            assert cfg.base_url is None

    def test_anthropic_uses_native_sdk(self):
        assert CLOUD_PROVIDERS["anthropic"].native_sdk == "anthropic"

    def test_non_anthropic_no_native_sdk(self):
        for key, cfg in CLOUD_PROVIDERS.items():
            if key != "anthropic":
                assert cfg.native_sdk is None


class TestAvailability:
    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False)
    def test_cloud_available_with_key(self):
        results = list_available()
        gemini = [(k, c, a, r) for k, c, a, r in results if k == "gemini"]
        assert len(gemini) == 1
        assert gemini[0][2] is True
        assert gemini[0][3] == "API key set"

    @patch.dict(os.environ, {}, clear=True)
    def test_cloud_unavailable_without_key(self):
        results = list_available()
        gemini = [(k, c, a, r) for k, c, a, r in results if k == "gemini"]
        assert len(gemini) == 1
        assert gemini[0][2] is False
        assert "no API key" in gemini[0][3]

    @patch("llm_eval.providers._check_ollama_model")
    def test_local_available_when_model_loaded(self, mock_check):
        mock_check.return_value = (True, "model loaded")
        results = list_available()
        ollama = [(k, c, a, r) for k, c, a, r in results if k == "ollama-qwen32b"]
        assert len(ollama) == 1
        assert ollama[0][2] is True


class TestCallProvider:
    @patch("llm_eval.providers._call_openai_compatible")
    def test_call_openai_compatible_provider(self, mock_call):
        from llm_eval.types import GenerationResult
        mock_call.return_value = GenerationResult(
            provider="gemini", model="gemini-pro", name="Gemini",
            tier="free", prompt_key="", prompt_label="",
            content="Hello!", elapsed_s=1.0,
        )
        cfg = ProviderConfig(
            key="gemini", name="Gemini", model="gemini-pro",
            tier="free", base_url="https://test.com", env_key="KEY",
        )
        result = call_provider(cfg, "Hello")
        assert result.content == "Hello!"
        assert result.error is None

    @patch("llm_eval.providers._call_anthropic")
    def test_call_anthropic_provider(self, mock_call):
        from llm_eval.types import GenerationResult
        mock_call.return_value = GenerationResult(
            provider="anthropic", model="claude", name="Claude",
            tier="$5", prompt_key="", prompt_label="",
            content="Hi there!", elapsed_s=2.0,
        )
        cfg = ProviderConfig(
            key="anthropic", name="Claude", model="claude",
            tier="$5", env_key="KEY", native_sdk="anthropic",
        )
        result = call_provider(cfg, "Hello")
        assert result.content == "Hi there!"

    @patch("llm_eval.providers._call_openai_compatible")
    def test_retry_on_failure(self, mock_call):
        mock_call.side_effect = [
            Exception("Connection error"),
            Exception("Connection error"),
            GenerationResult(
                provider="test", model="m", name="n", tier="t",
                prompt_key="", prompt_label="",
                content="Success!", elapsed_s=1.0,
            ),
        ]
        cfg = ProviderConfig(
            key="test", name="Test", model="m", tier="t",
            base_url="https://test.com", env_key="KEY",
        )
        result = call_provider(cfg, "Hello", max_retries=3, retry_delay=0.01)
        assert result.content == "Success!"
        assert mock_call.call_count == 3

    @patch("llm_eval.providers._call_openai_compatible")
    def test_returns_error_after_max_retries(self, mock_call):
        mock_call.side_effect = Exception("Persistent failure")
        cfg = ProviderConfig(
            key="test", name="Test", model="m", tier="t",
            base_url="https://test.com", env_key="KEY",
        )
        result = call_provider(cfg, "Hello", max_retries=2, retry_delay=0.01)
        assert result.error is not None
        assert "Persistent failure" in result.error
