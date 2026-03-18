"""
Provider registry, availability checks, and API call logic.

All providers use the OpenAI-compatible SDK except Anthropic (native SDK).
Local models go through Ollama's OpenAI-compatible API.
"""

from __future__ import annotations

import os
import time

from openai import OpenAI

from .types import GenerationResult, ProviderConfig

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

CLOUD_PROVIDERS: dict[str, ProviderConfig] = {
    "gemini": ProviderConfig(
        key="gemini",
        name="Google Gemini 3.1 Pro",
        model="gemini-3.1-pro-preview",
        tier="free",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        env_key="GEMINI_API_KEY",
    ),
    "deepseek": ProviderConfig(
        key="deepseek",
        name="DeepSeek V3.2",
        model="deepseek-chat",
        tier="free (5M tokens)",
        base_url="https://api.deepseek.com",
        env_key="DEEPSEEK_API_KEY",
    ),
    "xai": ProviderConfig(
        key="xai",
        name="xAI Grok 4.20",
        model="grok-4.20-beta-0309-non-reasoning",
        tier="$25 free credits",
        base_url="https://api.x.ai/v1",
        env_key="XAI_API_KEY",
    ),
    "openai": ProviderConfig(
        key="openai",
        name="OpenAI GPT-5.4",
        model="gpt-5.4",
        tier="$5 prepaid",
        base_url="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
    ),
    "anthropic": ProviderConfig(
        key="anthropic",
        name="Anthropic Claude Opus 4.6",
        model="claude-opus-4-6",
        tier="$5 prepaid",
        env_key="ANTHROPIC_API_KEY",
        native_sdk="anthropic",
    ),
}

LOCAL_PROVIDERS: dict[str, ProviderConfig] = {
    "ollama-qwen32b": ProviderConfig(
        key="ollama-qwen32b",
        name="Qwen 2.5 32B (local)",
        model="qwen2.5:32b-instruct-q5_K_M",
        tier="local",
    ),
    "ollama-qwen72b": ProviderConfig(
        key="ollama-qwen72b",
        name="Qwen 2.5 72B (local)",
        model="qwen2.5:72b-instruct-q4_K_M",
        tier="local",
    ),
    "ollama-llama70b": ProviderConfig(
        key="ollama-llama70b",
        name="Llama 3.1 70B (local)",
        model="llama3.1:70b-instruct-q4_K_M",
        tier="local",
    ),
    "ollama-nemo": ProviderConfig(
        key="ollama-nemo",
        name="Mistral Nemo 12B (local)",
        model="mistral-nemo:12b-instruct",
        tier="local",
    ),
    "ollama-mixtral": ProviderConfig(
        key="ollama-mixtral",
        name="Mixtral 8x7B (local)",
        model="mixtral:8x7b-instruct-v0.1-q4_K_M",
        tier="local",
    ),
    "ollama-deepseek32b": ProviderConfig(
        key="ollama-deepseek32b",
        name="DeepSeek-R1 32B (local)",
        model="deepseek-r1:32b",
        tier="local",
    ),
}

ALL_PROVIDERS: dict[str, ProviderConfig] = {**CLOUD_PROVIDERS, **LOCAL_PROVIDERS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ollama_url() -> str:
    """Get the Ollama OpenAI-compatible base URL."""
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def _get_ollama_native_url() -> str:
    """Get the Ollama native API base URL (for health checks)."""
    url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return url.rstrip("/v1").rstrip("/")


def _check_ollama_model(model: str) -> tuple[bool, str]:
    """Check if an Ollama model is available locally."""
    try:
        import httpx
        base = _get_ollama_native_url()
        resp = httpx.get(f"{base}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = model.split(":")[0] if ":" in model else model
            if any(model_base in m for m in models):
                return True, "model loaded"
            return False, f"Ollama running but model '{model}' not pulled"
    except Exception:
        return False, "Ollama not running"
    return False, "Ollama not running"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_all_providers() -> dict[str, ProviderConfig]:
    """Return all known providers."""
    return dict(ALL_PROVIDERS)


def list_available() -> list[tuple[str, ProviderConfig, bool, str]]:
    """Return (key, config, is_available, reason) for every known provider."""
    result = []
    for key, cfg in ALL_PROVIDERS.items():
        if key.startswith("ollama-"):
            avail, reason = _check_ollama_model(cfg.model)
        else:
            api_key = os.getenv(cfg.env_key or "", "").strip()
            if api_key:
                avail, reason = True, "API key set"
            else:
                avail, reason = False, "no API key"
        result.append((key, cfg, avail, reason))
    return result


def call_provider(
    config: ProviderConfig,
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 16384,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> GenerationResult:
    """Call a provider and return a GenerationResult.

    Retries on transient errors. Timeout: 120s cloud, 300s local.
    """
    timeout = 300.0 if config.key.startswith("ollama-") or config.native_sdk == "anthropic" else 180.0

    for attempt in range(max_retries):
        try:
            if config.native_sdk == "anthropic":
                return _call_anthropic(
                    config, prompt, system_prompt, temperature, max_tokens, timeout
                )
            else:
                return _call_openai_compatible(
                    config, prompt, system_prompt, temperature, max_tokens, timeout
                )
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                return GenerationResult(
                    provider=config.key,
                    model=config.model,
                    name=config.name,
                    tier=config.tier,
                    prompt_key="",
                    prompt_label="",
                    content="",
                    elapsed_s=0.0,
                    error=str(e),
                )


# ---------------------------------------------------------------------------
# Internal call functions
# ---------------------------------------------------------------------------

def _call_openai_compatible(
    config: ProviderConfig,
    prompt: str,
    system_prompt: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> GenerationResult:
    """Call a provider using the OpenAI-compatible API."""
    if config.key.startswith("ollama-"):
        base_url = _get_ollama_url()
        api_key = "ollama"
    else:
        base_url = config.base_url
        api_key = os.getenv(config.env_key or "", "")

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    t0 = time.perf_counter()
    # OpenAI GPT-5+ requires max_completion_tokens instead of max_tokens
    if config.key == "openai":
        token_param = {"max_completion_tokens": max_tokens}
    else:
        token_param = {"max_tokens": max_tokens}
    response = client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=temperature,
        **token_param,
    )
    elapsed = time.perf_counter() - t0

    msg = response.choices[0].message.content
    usage = response.usage
    return GenerationResult(
        provider=config.key,
        model=config.model,
        name=config.name,
        tier=config.tier,
        prompt_key="",
        prompt_label="",
        content=msg or "",
        elapsed_s=round(elapsed, 2),
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
    )


def _call_anthropic(
    config: ProviderConfig,
    prompt: str,
    system_prompt: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> GenerationResult:
    """Call Anthropic using its native SDK."""
    import anthropic

    api_key = os.getenv(config.env_key or "", "")
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    kwargs: dict = {
        "model": config.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    # Extended thinking disabled — burns tokens even on timeout.
    # To re-enable: uncomment below and set timeout high enough.
    # kwargs["temperature"] = 1
    # kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}

    t0 = time.perf_counter()
    response = client.messages.create(**kwargs)
    elapsed = time.perf_counter() - t0

    # Extract text content (skip thinking blocks)
    msg = ""
    for block in response.content:
        if block.type == "text":
            msg = block.text
            break
    return GenerationResult(
        provider=config.key,
        model=config.model,
        name=config.name,
        tier=config.tier,
        prompt_key="",
        prompt_label="",
        content=msg,
        elapsed_s=round(elapsed, 2),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
