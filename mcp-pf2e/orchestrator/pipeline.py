"""End-to-end PF2e character build pipeline.

Decompose → Prompt → Generate (local LLM) → Validate → Repair loop.
"""

import json
import sys
import time
from pathlib import Path

import httpx
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "llm-eval"))

from query.decomposer import get_build_options
from query.types import BuildOptions
from validator.engine import BuildValidator
from validator.repair import format_repair_prompt
from orchestrator.prompt_builder import build_system_prompt, build_generation_prompt

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_OPENAI_URL = f"{OLLAMA_BASE_URL}/v1"

LOCAL_MODELS = {
    "ollama-qwen3-32b": "qwen3:32b",
    "ollama-qwen32b": "qwen2.5:32b-instruct-q5_K_M",
    "ollama-deepseek32b": "deepseek-r1:32b",
    "ollama-llama70b": "llama3.1:70b-instruct-q4_K_M",
    "ollama-nemo": "mistral-nemo:12b-instruct",
}

LARGE_MODELS = {"ollama-qwen3-32b", "ollama-qwen32b", "ollama-deepseek32b", "ollama-llama70b"}


def _unload_all_models():
    """Unload all models from Ollama to free VRAM."""
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5)
        if resp.status_code == 200:
            running = resp.json().get("models", [])
            for m in running:
                name = m.get("name", "")
                if name:
                    httpx.post(
                        f"{OLLAMA_BASE_URL}/api/generate",
                        json={"model": name, "keep_alive": 0},
                        timeout=10,
                    )
    except Exception:
        pass


def _call_ollama(
    model: str,
    prompt: str,
    system_prompt: str,
    temperature: float = 0.7,
    json_mode: bool = True,
    max_tokens: int = 8192,
) -> tuple[str, float]:
    """Call Ollama via OpenAI-compatible API. Returns (content, elapsed_seconds)."""
    client = OpenAI(base_url=OLLAMA_OPENAI_URL, api_key="ollama")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    extra = {"extra_body": {"options": {"num_ctx": 8192}}}
    if json_mode:
        extra["response_format"] = {"type": "json_object"}

    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **extra,
    )
    elapsed = time.perf_counter() - t0

    content = response.choices[0].message.content or ""
    return content, round(elapsed, 2)


def run_build(
    class_name: str,
    character_level: int,
    ancestry_name: str = "",
    dedications: list[str] | None = None,
    request: str = "",
    provider_key: str = "ollama-qwen3-32b",
    max_repairs: int = 2,
    temperature: float = 0.7,
    repair_temperature: float = 0.5,
    output_format: str = "json",
    skip_semantic: bool | None = None,
    verbose: bool = True,
) -> dict:
    """Full build pipeline.

    Returns dict with build_text, build_json, validation, attempts, timings.
    """
    model = LOCAL_MODELS.get(provider_key, provider_key)
    json_mode = output_format == "json"

    if skip_semantic is None:
        skip_semantic = provider_key in LARGE_MODELS

    if not request:
        ded_str = f" with {', '.join(d.title() for d in dedications)} Dedication" if dedications else ""
        request = f"Level {character_level} {ancestry_name.title()} {class_name.title()}{ded_str}"

    timings = {}
    result = {
        "request": request,
        "provider": provider_key,
        "model": model,
        "format": output_format,
    }

    # Step 1: Unload models to free VRAM
    if verbose:
        print(f"[pipeline] Unloading models to free VRAM...")
    _unload_all_models()

    # Step 2: Decompose build options
    if verbose:
        print(f"[pipeline] Decomposing build: {request}")
    t0 = time.time()
    options = get_build_options(class_name, character_level, ancestry_name, dedications)
    timings["decompose"] = round(time.time() - t0, 2)

    total_opts = sum(len(so.options) for so in options.slot_options)
    if verbose:
        print(f"[pipeline] Found {len(options.slot_options)} feat slots, {total_opts} total options")

    # Step 3: Build prompt
    t0 = time.time()
    system_prompt = build_system_prompt()
    generation_prompt = build_generation_prompt(request, options, output_format)
    timings["prompt_build"] = round(time.time() - t0, 2)

    if verbose:
        print(f"[pipeline] Prompt: {len(generation_prompt)} chars")

    # Step 4: Generate
    if verbose:
        print(f"[pipeline] Generating with {model} (temperature={temperature})...")
    raw_output, gen_time = _call_ollama(model, generation_prompt, system_prompt, temperature, json_mode)
    timings["generate"] = gen_time

    if verbose:
        print(f"[pipeline] Generated {len(raw_output)} chars in {gen_time}s")

    # Step 5: Validate
    if verbose:
        print(f"[pipeline] Validating...")

    t0 = time.time()
    try:
        from server.db import PF2eDB
        db = PF2eDB()
    except Exception:
        db = None

    validator = BuildValidator(db=db, skip_semantic=skip_semantic)
    build_json = None

    if json_mode:
        try:
            build_json = json.loads(raw_output)
            validation = validator.validate_json(
                build_json,
                expected_class=class_name,
                expected_ancestry=ancestry_name,
                expected_level=character_level,
            )
        except json.JSONDecodeError:
            validation = validator.validate(
                raw_output,
                expected_class=class_name,
                expected_ancestry=ancestry_name,
                expected_level=character_level,
            )
    else:
        validation = validator.validate(
            raw_output,
            expected_class=class_name,
            expected_ancestry=ancestry_name,
            expected_level=character_level,
        )
    timings["validate"] = round(time.time() - t0, 2)

    if verbose:
        print(f"[pipeline] Validation: {validation.error_count} errors, {len(validation.warnings)} warnings")

    # Step 6: Repair loop
    attempts = 1
    current_output = raw_output

    for i in range(max_repairs):
        if validation.is_valid:
            break

        if verbose:
            print(f"[pipeline] Repair attempt {i + 1}/{max_repairs}...")
            for e in validation.errors:
                print(f"  ERROR: {e.message}")

        repair_prompt = format_repair_prompt(validation, request)
        repair_input = f"{current_output}\n\n---\n\n{repair_prompt}"

        t0 = time.time()
        current_output, repair_time = _call_ollama(
            model, repair_input, system_prompt, repair_temperature, json_mode,
        )
        timings[f"repair_{i + 1}"] = repair_time
        attempts += 1

        if verbose:
            print(f"[pipeline] Repair generated {len(current_output)} chars in {repair_time}s")

        t0v = time.time()
        if json_mode:
            try:
                build_json = json.loads(current_output)
                validation = validator.validate_json(
                    build_json,
                    expected_class=class_name,
                    expected_ancestry=ancestry_name,
                    expected_level=character_level,
                )
            except json.JSONDecodeError:
                validation = validator.validate(
                    current_output,
                    expected_class=class_name,
                    expected_ancestry=ancestry_name,
                    expected_level=character_level,
                )
        else:
            validation = validator.validate(
                current_output,
                expected_class=class_name,
                expected_ancestry=ancestry_name,
                expected_level=character_level,
            )
        timings[f"validate_{i + 1}"] = round(time.time() - t0v, 2)

        if verbose:
            print(f"[pipeline] Post-repair: {validation.error_count} errors, {len(validation.warnings)} warnings")

    # Final result
    result["build_text"] = current_output
    result["build_json"] = build_json
    result["validation"] = {
        "is_valid": validation.is_valid,
        "errors": [{"rule": e.rule, "message": e.message} for e in validation.errors],
        "warnings": [{"rule": w.rule, "message": w.message} for w in validation.warnings],
        "verified_feats": validation.verified_feats,
    }
    result["attempts"] = attempts
    result["timings"] = timings

    if verbose:
        status = "VALID" if validation.is_valid else f"INVALID ({validation.error_count} errors)"
        print(f"\n[pipeline] Final: {status} after {attempts} attempt(s)")
        print(f"[pipeline] Timings: {json.dumps(timings)}")

    return result
