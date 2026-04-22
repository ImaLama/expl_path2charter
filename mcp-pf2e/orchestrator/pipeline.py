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
from orchestrator.prompt_builder import (
    build_system_prompt, build_generation_prompt, build_skeleton_prompts,
    build_skeleton_schema, build_response_schema,
)

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
THINKING_MODELS = {"ollama-qwen3-32b", "ollama-deepseek32b"}


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
    response_schema: dict | None = None,
    max_tokens: int = 2048,
) -> tuple[str, float, dict]:
    """Call Ollama via OpenAI-compatible API. Returns (content, elapsed_seconds, usage)."""
    client = OpenAI(base_url=OLLAMA_OPENAI_URL, api_key="ollama")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    extra = {"extra_body": {"options": {"num_ctx": 8192}}}
    if response_schema:
        extra["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "CharacterBuild",
                "strict": True,
                "schema": response_schema,
            },
        }
    elif json_mode:
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
    usage = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return content, round(elapsed, 2), usage


def run_build(
    class_name: str = "",
    character_level: int = 0,
    ancestry_name: str = "",
    dedications: list[str] | None = None,
    request: str = "",
    provider_key: str = "ollama-qwen3-32b",
    max_repairs: int = 2,
    temperature: float = 0.7,
    repair_temperature: float = 0.5,
    output_format: str = "json",
    verbose: bool = True,
) -> dict:
    """Full build pipeline with optional two-pass mode.

    If class_name and character_level are provided, skips the skeleton pass.
    Otherwise, Pass 1 asks the LLM to choose class/ancestry/level from the concept.
    """
    model = LOCAL_MODELS.get(provider_key, provider_key)
    json_mode = output_format == "json"

    if not request and class_name:
        ded_str = f" with {', '.join(d.title() for d in (dedications or []))} Dedication" if dedications else ""
        anc_str = f"{ancestry_name.title()} " if ancestry_name else ""
        request = f"Level {character_level} {anc_str}{class_name.title()}{ded_str}"

    timings = {}
    all_usages = []
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

    # Step 1.5: Skeleton pass if class/level not fully specified
    if not class_name or not character_level:
        if verbose:
            print(f"[pipeline] Pass 1: Generating build skeleton from concept...")
        skeleton_system, skeleton_user = build_skeleton_prompts(
            request, class_name=class_name, ancestry_name=ancestry_name, level=character_level,
        )
        skeleton_schema = build_skeleton_schema()
        t0 = time.time()
        skeleton_raw, skeleton_time, skeleton_usage = _call_ollama(
            model, skeleton_user, skeleton_system, 0.7,
            response_schema=skeleton_schema, max_tokens=512,
        )
        timings["skeleton"] = skeleton_time
        all_usages.append(skeleton_usage)

        try:
            skeleton = json.loads(skeleton_raw)
        except json.JSONDecodeError:
            skeleton = {}

        if verbose:
            print(f"[pipeline] Skeleton: {json.dumps(skeleton, indent=2)}")

        if not class_name:
            class_name = skeleton.get("class", "").lower()
        if not ancestry_name:
            ancestry_name = skeleton.get("ancestry", "").lower()
        if not character_level:
            character_level = skeleton.get("level", 5)
        result["skeleton"] = skeleton

        if not class_name:
            result["error"] = "Could not determine class from concept"
            return result

    # Step 1.6: Pre-validate skeleton before expensive generation
    from query.static_reader import list_available_classes, list_available_ancestries
    available_classes = list_available_classes()
    if class_name and class_name not in available_classes:
        msg = f"Class '{class_name}' not found in data. Available: {', '.join(available_classes[:10])}"
        if verbose:
            print(f"[pipeline] ERROR: {msg}")
        result["error"] = msg
        return result
    available_ancestries = list_available_ancestries()
    if ancestry_name and ancestry_name not in available_ancestries:
        msg = f"Ancestry '{ancestry_name}' not found in data. Available: {', '.join(available_ancestries[:10])}"
        if verbose:
            print(f"[pipeline] ERROR: {msg}")
        result["error"] = msg
        return result

    # Step 2: Decompose build options
    if verbose:
        print(f"[pipeline] Decomposing build: {class_name.title()} lvl {character_level}" +
              (f" ({ancestry_name.title()})" if ancestry_name else ""))
    t0 = time.time()
    options = get_build_options(class_name, character_level, ancestry_name, dedications)
    timings["decompose"] = round(time.time() - t0, 2)

    total_opts = sum(len(so.options) for so in options.slot_options)
    if verbose:
        print(f"[pipeline] Found {len(options.slot_options)} feat slots, {total_opts} total options")

    # Step 3: Build prompt + schema (schema cached for repair reuse)
    t0 = time.time()
    system_prompt = build_system_prompt()
    generation_prompt = build_generation_prompt(request, options, output_format)
    response_schema = build_response_schema(options) if json_mode else None
    timings["prompt_build"] = round(time.time() - t0, 2)

    if verbose:
        print(f"[pipeline] Prompt: {len(generation_prompt)} chars")
        if response_schema:
            enum_slots = sum(
                1 for lvl in response_schema.get("properties", {}).get("levels", {}).get("properties", {}).values()
                for prop in lvl.get("properties", {}).values()
                if "enum" in prop
            )
            print(f"[pipeline] Schema: {enum_slots} enum-constrained feat slots")

    # Step 4: Generate (lower temperature with schema enforcement)
    gen_temp = 0.5 if response_schema else temperature
    # Thinking models (qwen3, deepseek-r1) use hidden tokens — need higher budget
    gen_max_tokens = 4096 if provider_key in THINKING_MODELS else 2048
    if verbose:
        print(f"[pipeline] Generating with {model} (temperature={gen_temp}, schema={'ON' if response_schema else 'OFF'})...")
    raw_output, gen_time, gen_usage = _call_ollama(
        model, generation_prompt, system_prompt, gen_temp,
        response_schema=response_schema, max_tokens=gen_max_tokens,
    )
    timings["generate"] = gen_time
    all_usages.append(gen_usage)

    if verbose:
        print(f"[pipeline] Generated {len(raw_output)} chars in {gen_time}s")

    # Step 5: Validate
    if verbose:
        print(f"[pipeline] Validating...")

    t0 = time.time()
    validator = BuildValidator()
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

    # Step 6: Repair loop with cumulative history
    attempts = 1
    current_output = raw_output
    repair_history = []

    for i in range(max_repairs):
        if validation.is_valid:
            break

        if verbose:
            print(f"[pipeline] Repair attempt {i + 1}/{max_repairs}...")
            for e in validation.errors:
                print(f"  ERROR: {e.message}")

        # Record this attempt's errors in history
        repair_history.append({
            "attempt": attempts,
            "errors": [
                {"rule": e.rule, "message": e.message, "feat_name": e.feat_name}
                for e in validation.errors
            ],
        })

        repair_prompt = format_repair_prompt(validation, request, history=repair_history)
        repair_input = f"{current_output}\n\n---\n\n{repair_prompt}"

        t0 = time.time()
        repair_max = 2048 if provider_key in THINKING_MODELS else 1024
        current_output, repair_time, repair_usage = _call_ollama(
            model, repair_input, system_prompt, repair_temperature,
            response_schema=response_schema, max_tokens=repair_max,
        )
        timings[f"repair_{i + 1}"] = repair_time
        all_usages.append(repair_usage)
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

    token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in all_usages:
        for k in token_totals:
            token_totals[k] += u.get(k, 0)
    result["tokens"] = token_totals

    if verbose:
        status = "VALID" if validation.is_valid else f"INVALID ({validation.error_count} errors)"
        print(f"\n[pipeline] Final: {status} after {attempts} attempt(s)")
        print(f"[pipeline] Timings: {json.dumps(timings)}")

    return result
