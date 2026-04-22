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

from query.decomposer import get_build_options
from query.types import BuildOptions
from query.static_reader import get_feat_data, group_skill_feats_by_skill
from validator.engine import BuildValidator
from validator.repair import format_repair_prompt
from orchestrator.prompt_builder import (
    build_system_prompt, build_generation_prompt, build_skeleton_prompts,
    build_skeleton_schema, build_response_schema,
    narrow_skill_feat_enums,
    build_plan_schema, build_plan_prompt, build_guided_schema, build_guided_prompt,
    _PLAN_SYSTEM_PROMPT,
)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_OPENAI_URL = f"{OLLAMA_BASE_URL}/v1"

LOCAL_MODELS = {
    "ollama-qwen3-32b": "qwen3:32b",
    "ollama-qwen32b": "qwen2.5:32b-instruct-q5_K_M",
    "ollama-qwen25-coder": "qwen2.5-coder:32b-instruct-q6_K",
    "ollama-deepseek32b": "deepseek-r1:32b",
    "ollama-llama70b": "llama3.1:70b-instruct-q4_K_M",
    "ollama-nemo": "mistral-nemo:12b-instruct",
    "ollama-mistral-small": "mistral-small3.2:24b",
}

LARGE_MODELS = {"ollama-qwen3-32b", "ollama-qwen32b", "ollama-qwen25-coder", "ollama-deepseek32b", "ollama-llama70b"}
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
    finish_reason = response.choices[0].finish_reason or ""
    usage = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "finish_reason": finish_reason,
        }
    return content, round(elapsed, 2), usage


def _run_planned_generation(
    model: str,
    options,
    request: str,
    character_level: int,
    class_name: str,
    ancestry_name: str,
    provider_key: str,
    temperature: float,
    repair_temperature: float,
    verbose: bool,
    ranked_feats,
    all_usages: list,
    timings: dict,
) -> dict | None:
    """Two-pass generation: plan feats first, then fill in build details.

    Returns a result dict on success, or None to fall back to single-pass.
    """
    # --- Pass 1: Feat Plan ---
    if verbose:
        print(f"[pipeline] Pass 1: Planning feat selections...")

    t0 = time.time()
    plan_prompt = build_plan_prompt(request, options, ranked_feats=ranked_feats)
    plan_schema = build_plan_schema(options)
    plan_max = 2048 if provider_key in THINKING_MODELS else 1024

    plan_raw, plan_time, plan_usage = _call_ollama(
        model, plan_prompt, _PLAN_SYSTEM_PROMPT, temperature,
        response_schema=plan_schema, max_tokens=plan_max,
    )
    timings["plan"] = plan_time
    all_usages.append(plan_usage)

    if verbose:
        print(f"[pipeline] Plan generated in {plan_time}s ({len(plan_raw)} chars)")
        if plan_usage.get("finish_reason") == "length":
            print(f"[pipeline] WARNING: Plan hit token limit ({plan_max})")
        if len(plan_raw) < 50:
            print(f"[pipeline] WARNING: Plan too short: {plan_raw}")

    try:
        plan_json = json.loads(plan_raw)
    except json.JSONDecodeError:
        if verbose:
            print(f"[pipeline] Plan JSON parse failed, falling back")
        return None

    planned_feats = plan_json.get("levels", plan_json)

    # --- Validate the plan ---
    if verbose:
        print(f"[pipeline] Validating feat plan...")

    validator = BuildValidator()
    from validator.types import ParsedBuild, ParsedFeatChoice

    plan_build = ParsedBuild(
        class_name=class_name,
        ancestry_name=ancestry_name,
        character_level=character_level,
    )
    plan_feats = []
    for level_str, slots in planned_feats.items():
        if not isinstance(slots, dict):
            continue
        for slot_key, feat_name in slots.items():
            if not feat_name:
                continue
            slot_type = slot_key.replace("_feat", "")
            plan_feats.append(ParsedFeatChoice(
                name=feat_name, slot_type=slot_type, character_level=int(level_str),
            ))
    plan_build.feats = plan_feats
    plan_validation = validator._run_rules(plan_build)

    if verbose:
        print(f"[pipeline] Plan: {plan_validation.error_count} errors, {len(plan_validation.warnings)} warnings")

    # --- Repair plan if needed (1 attempt) ---
    if not plan_validation.is_valid:
        if verbose:
            for e in plan_validation.errors:
                print(f"  PLAN ERROR: {e.message}")
            print(f"[pipeline] Repairing feat plan...")

        import copy
        repair_plan_schema = copy.deepcopy(plan_schema)

        # Aggressive dedup: for each feat, keep it only in the first level's enum
        _REPEATABLE = {"additional lore", "assurance", "skill training"}
        feat_first_level: dict[str, int] = {}
        for level_str in sorted(planned_feats, key=lambda x: int(x)):
            slots = planned_feats[level_str]
            if not isinstance(slots, dict):
                continue
            for feat_name in slots.values():
                if feat_name and feat_name.lower() not in _REPEATABLE:
                    if feat_name.lower() not in feat_first_level:
                        feat_first_level[feat_name.lower()] = int(level_str)

        levels_props = repair_plan_schema.get("properties", {}).get("levels", {}).get("properties", {})
        removed = 0
        for level_str, level_schema in levels_props.items():
            lvl = int(level_str)
            for slot_schema in level_schema.get("properties", {}).values():
                if "enum" not in slot_schema:
                    continue
                orig = len(slot_schema["enum"])
                slot_schema["enum"] = [
                    f for f in slot_schema["enum"]
                    if f.lower() in _REPEATABLE
                    or f.lower() not in feat_first_level
                    or feat_first_level[f.lower()] >= lvl
                ]
                removed += orig - len(slot_schema["enum"])
        if verbose and removed:
            print(f"[pipeline] Plan repair: removed {removed} already-taken feats from later enums")

        repair_prompt = format_repair_prompt(plan_validation, request)
        repair_input = f"{plan_raw}\n\n---\n\n{repair_prompt}"

        plan_raw, repair_time, repair_usage = _call_ollama(
            model, repair_input, _PLAN_SYSTEM_PROMPT, repair_temperature,
            response_schema=repair_plan_schema, max_tokens=plan_max,
        )
        timings["plan_repair"] = repair_time
        all_usages.append(repair_usage)

        try:
            plan_json = json.loads(plan_raw)
            planned_feats = plan_json.get("levels", plan_json)
        except json.JSONDecodeError:
            if verbose:
                print(f"[pipeline] Plan repair parse failed, falling back")
            return None

        # Re-validate
        plan_build.feats = []
        for level_str, slots in planned_feats.items():
            if not isinstance(slots, dict):
                continue
            for slot_key, feat_name in slots.items():
                if not feat_name:
                    continue
                slot_type = slot_key.replace("_feat", "")
                plan_build.feats.append(ParsedFeatChoice(
                    name=feat_name, slot_type=slot_type, character_level=int(level_str),
                ))
        plan_validation = validator._run_rules(plan_build)
        if verbose:
            print(f"[pipeline] Plan after repair: {plan_validation.error_count} errors")

    # --- Collect constraints for full build ---
    constraints = []
    for feat in plan_build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        prereqs = entry.get("system", {}).get("prerequisites", {}).get("value", [])
        for p in prereqs:
            pval = p.get("value", "") if isinstance(p, dict) else str(p)
            if not pval:
                continue
            # Flag ability score and skill requirements
            pval_lower = pval.lower()
            if any(a in pval_lower for a in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]):
                constraints.append(f"{feat.name} requires: {pval}")
            elif "trained in" in pval_lower or "expert in" in pval_lower:
                constraints.append(f"{feat.name} requires: {pval}")

    if verbose and constraints:
        print(f"[pipeline] {len(constraints)} constraints forwarded to full build")

    # --- Pass 2: Guided full build ---
    if verbose:
        print(f"[pipeline] Pass 2: Generating full build with planned feats...")

    t0 = time.time()
    guided_prompt = build_guided_prompt(request, options, planned_feats, constraints=constraints)
    guided_schema = build_guided_schema(options, planned_feats)
    gen_max = 4096 if provider_key in THINKING_MODELS else 2048

    raw_output, gen_time, gen_usage = _call_ollama(
        model, guided_prompt, build_system_prompt(), 0.5,
        response_schema=guided_schema, max_tokens=gen_max,
    )
    timings["generate"] = gen_time
    all_usages.append(gen_usage)

    if verbose:
        print(f"[pipeline] Build generated in {gen_time}s ({len(raw_output)} chars)")

    # --- Validate full build ---
    t0 = time.time()
    build_json = None
    try:
        build_json = json.loads(raw_output)
        validation = validator.validate_json(
            build_json,
            expected_class=class_name,
            expected_ancestry=ancestry_name,
            expected_level=character_level,
        )
    except json.JSONDecodeError:
        if verbose:
            print(f"[pipeline] WARNING: Guided build JSON parse failed")
        return None
    timings["validate"] = round(time.time() - t0, 2)

    if verbose:
        print(f"[pipeline] Validation: {validation.error_count} errors, {len(validation.warnings)} warnings")

    # --- One repair attempt if needed ---
    attempts = 1
    if not validation.is_valid:
        if verbose:
            print(f"[pipeline] Repair attempt (guided)...")
            for e in validation.errors:
                print(f"  ERROR: {e.message}")

        repair_prompt = format_repair_prompt(validation, request)
        repair_input = f"{raw_output}\n\n---\n\n{repair_prompt}"
        repair_max = 2048 if provider_key in THINKING_MODELS else 1024

        raw_output, repair_time, repair_usage = _call_ollama(
            model, repair_input, build_system_prompt(), repair_temperature,
            response_schema=guided_schema, max_tokens=repair_max,
        )
        timings["repair_1"] = repair_time
        all_usages.append(repair_usage)
        attempts += 1

        try:
            build_json = json.loads(raw_output)
            validation = validator.validate_json(
                build_json,
                expected_class=class_name,
                expected_ancestry=ancestry_name,
                expected_level=character_level,
            )
        except json.JSONDecodeError:
            pass

        if verbose:
            print(f"[pipeline] Post-repair: {validation.error_count} errors")

    # --- Aggregate tokens ---
    token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in all_usages:
        for k in token_totals:
            token_totals[k] += u.get(k, 0)

    status = "VALID" if validation.is_valid else f"INVALID ({validation.error_count} errors)"
    if verbose:
        print(f"\n[pipeline] Final: {status} after {attempts} attempt(s) (planned)")
        print(f"[pipeline] Timings: {json.dumps(timings)}")

    return {
        "build_text": raw_output,
        "build_json": build_json,
        "validation": {
            "is_valid": validation.is_valid,
            "errors": [{"rule": e.rule, "message": e.message} for e in validation.errors],
            "warnings": [{"rule": w.rule, "message": w.message} for w in validation.warnings],
            "verified_feats": validation.verified_feats,
        },
        "attempts": attempts,
        "timings": timings,
        "tokens": token_totals,
        "planned_feats": planned_feats,
    }


def run_build(
    class_name: str = "",
    character_level: int = 0,
    ancestry_name: str = "",
    dedications: list[str] | None = None,
    request: str = "",
    provider_key: str = "ollama-mistral-small",
    max_repairs: int = 2,
    temperature: float = 0.7,
    repair_temperature: float = 0.5,
    output_format: str = "json",
    use_vector_ranking: bool = False,
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

    # Step 1.5: Skeleton pass if class/level/ancestry not fully specified
    if not class_name or not character_level or not ancestry_name:
        if verbose:
            print(f"[pipeline] Pass 1: Generating build skeleton from concept...")
        skeleton_system, skeleton_user = build_skeleton_prompts(
            request, class_name=class_name, ancestry_name=ancestry_name, level=character_level,
        )
        skeleton_schema = build_skeleton_schema()
        t0 = time.time()
        skeleton_raw, skeleton_time, skeleton_usage = _call_ollama(
            model, skeleton_user, skeleton_system, 0.7,
            response_schema=skeleton_schema,
            max_tokens=1024 if provider_key in THINKING_MODELS else 512,
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

    # Step 2.5: Rank feats by concept relevance (optional, requires ChromaDB + mxbai)
    ranked_feats = None
    if use_vector_ranking:
        try:
            from query.feat_ranker import rank_feats_for_concept

            if verbose:
                print(f"[pipeline] Ranking feats by concept relevance via ChromaDB...")
            t0_rank = time.time()
            ranked_feats = rank_feats_for_concept(request, options)
            timings["ranking"] = round(time.time() - t0_rank, 2)

            ranked_count = sum(
                len([r for r in v if r.get("show_description")])
                for v in ranked_feats.values()
            )
            if verbose:
                print(f"[pipeline] Ranked {len(ranked_feats)} slots, {ranked_count} feats with descriptions ({timings['ranking']}s)")

            # Unload mxbai for large models that need full VRAM
            if provider_key in LARGE_MODELS:
                _unload_all_models()
        except Exception:
            import traceback
            if verbose:
                print(f"[pipeline] WARNING: Vector ranking failed, proceeding without ranking")
                traceback.print_exc()
            ranked_feats = None

    # Step 2.7: Use planned generation for high-slot builds
    total_slots = len(options.slot_options)
    if total_slots > 6 and json_mode:
        if verbose:
            print(f"[pipeline] High slot count ({total_slots}) — using feat planning pass")
        planned_result = _run_planned_generation(
            model=model, options=options, request=request,
            character_level=character_level, class_name=class_name,
            ancestry_name=ancestry_name, provider_key=provider_key,
            temperature=temperature, repair_temperature=repair_temperature,
            verbose=verbose, ranked_feats=ranked_feats,
            all_usages=all_usages, timings=timings,
        )
        if planned_result is not None:
            result.update(planned_result)
            return result

        if verbose:
            print(f"[pipeline] Planned generation failed, falling back to single-pass")

    # Step 3: Build prompt + schema (schema cached for repair reuse)
    t0 = time.time()
    system_prompt = build_system_prompt()
    generation_prompt = build_generation_prompt(request, options, output_format, ranked_feats=ranked_feats)
    response_schema = build_response_schema(options) if json_mode else None
    timings["prompt_build"] = round(time.time() - t0, 2)

    if verbose:
        print(f"[pipeline] Prompt: {len(generation_prompt)} chars")
        if response_schema:
            enum_sizes = [
                len(prop.get("enum", []))
                for lvl in response_schema.get("properties", {}).get("levels", {}).get("properties", {}).values()
                for prop in lvl.get("properties", {}).values()
                if "enum" in prop
            ]
            print(f"[pipeline] Schema: {len(enum_sizes)} enum-constrained feat slots (largest: {max(enum_sizes)} options)")

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
        if gen_usage.get("finish_reason") == "length":
            print(f"[pipeline] WARNING: Generation hit token limit ({gen_max_tokens}) — output likely truncated")
        if len(raw_output) < 100:
            print(f"[pipeline] WARNING: Unusually short output ({len(raw_output)} chars): {raw_output[:100]}")

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
        except json.JSONDecodeError as exc:
            if verbose:
                print(f"[pipeline] WARNING: JSON parse failed ({exc}), falling back to text parsing")
                print(f"[pipeline] Raw output ({len(raw_output)} chars): {raw_output[:200]}...")
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
            dupes = [e for e in validation.errors if e.rule == "duplicate_feat"]
            if dupes:
                dupe_names = set(e.feat_name for e in dupes if e.feat_name)
                print(f"  DUPLICATES: {len(dupes)} duplicate errors ({', '.join(sorted(dupe_names))})")
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

        # Extract build state for narrowed repair schema
        repair_schema = response_schema
        valid_skill_feats = None
        try:
            current_build = json.loads(current_output)

            # Narrow skill feat enums based on actual trained skills
            skills = current_build.get("skills", {})
            trained_skills = [
                skill for skill, rank in skills.items()
                if rank.lower() in ("trained", "expert", "master", "legendary")
            ]
            if trained_skills and response_schema:
                repair_schema = narrow_skill_feat_enums(
                    response_schema, trained_skills, character_level,
                )
                grouped = group_skill_feats_by_skill(trained_skills, character_level)
                valid_skill_feats = {k: [f.name for f in v] for k, v in grouped.items()}
                if verbose:
                    total_narrowed = sum(len(v) for v in valid_skill_feats.values())
                    print(f"[pipeline] Narrowed skill feats to {total_narrowed} options for {len(trained_skills)} trained skills")

            # Prevent ALL duplicates: remove every taken feat from later levels' enums
            import copy
            _REPEATABLE = {"additional lore", "assurance", "skill training"}
            levels_data = current_build.get("levels", {})
            feat_at_level: dict[str, int] = {}  # feat_name_lower → level where taken
            for level_str in sorted(levels_data, key=lambda x: int(x)):
                slots = levels_data[level_str]
                if not isinstance(slots, dict):
                    continue
                for slot_key, feat_name in slots.items():
                    if not feat_name:
                        continue
                    name_lower = feat_name.lower()
                    if name_lower not in _REPEATABLE and name_lower not in feat_at_level:
                        feat_at_level[name_lower] = int(level_str)

            if feat_at_level:
                if repair_schema is response_schema:
                    repair_schema = copy.deepcopy(response_schema)
                levels_props = repair_schema.get("properties", {}).get("levels", {}).get("properties", {})
                removed_count = 0
                for level_str, level_schema in levels_props.items():
                    lvl = int(level_str)
                    for slot_schema in level_schema.get("properties", {}).values():
                        if "enum" not in slot_schema:
                            continue
                        original_len = len(slot_schema["enum"])
                        slot_schema["enum"] = [
                            f for f in slot_schema["enum"]
                            if f.lower() in _REPEATABLE or f.lower() not in feat_at_level or feat_at_level[f.lower()] >= lvl
                        ]
                        removed_count += original_len - len(slot_schema["enum"])
                if verbose and removed_count:
                    print(f"[pipeline] Prevented duplicates: removed {removed_count} already-taken feats from later level enums")

            # Dedication-aware repair: remove invalid second dedication from enums
            dedications_in_build = []
            archetype_feat_count = 0
            for level_str in sorted(levels_data, key=lambda x: int(x)):
                slots = levels_data[level_str]
                if not isinstance(slots, dict):
                    continue
                for slot_key, feat_name in slots.items():
                    if not feat_name:
                        continue
                    entry = get_feat_data(feat_name)
                    if not entry:
                        continue
                    traits = entry.get("system", {}).get("traits", {}).get("value", [])
                    traits_lower = [t.lower() for t in traits]
                    if "dedication" in traits_lower:
                        dedications_in_build.append({"name": feat_name, "level": int(level_str)})
                    elif "archetype" in traits_lower:
                        archetype_feat_count += 1

            if len(dedications_in_build) >= 2 and archetype_feat_count < 2:
                second_ded = dedications_in_build[1]
                if repair_schema is response_schema:
                    repair_schema = copy.deepcopy(response_schema)
                levels_props = repair_schema.get("properties", {}).get("levels", {}).get("properties", {})
                for level_str, level_schema in levels_props.items():
                    for slot_schema in level_schema.get("properties", {}).values():
                        if "enum" in slot_schema and second_ded["name"] in slot_schema["enum"]:
                            slot_schema["enum"].remove(second_ded["name"])
                if verbose:
                    print(f"[pipeline] Removed invalid 2nd dedication '{second_ded['name']}' from all repair enums (need 2 archetype feats from {dedications_in_build[0]['name']} first)")
        except (json.JSONDecodeError, AttributeError):
            pass

        repair_prompt = format_repair_prompt(
            validation, request, history=repair_history,
            valid_skill_feats=valid_skill_feats,
        )
        repair_input = f"{current_output}\n\n---\n\n{repair_prompt}"

        t0 = time.time()
        repair_max = 2048 if provider_key in THINKING_MODELS else 1024
        current_output, repair_time, repair_usage = _call_ollama(
            model, repair_input, system_prompt, repair_temperature,
            response_schema=repair_schema, max_tokens=repair_max,
        )
        timings[f"repair_{i + 1}"] = repair_time
        all_usages.append(repair_usage)
        attempts += 1

        if verbose:
            print(f"[pipeline] Repair generated {len(current_output)} chars in {repair_time}s")
            if repair_usage.get("finish_reason") == "length":
                print(f"[pipeline] WARNING: Repair hit token limit ({repair_max}) — output likely truncated")
            if len(current_output) == 0:
                print(f"[pipeline] WARNING: Empty repair output — likely token budget exhaustion (thinking consumed all {repair_max} tokens)")
            elif len(current_output) < 100:
                print(f"[pipeline] WARNING: Unusually short repair output ({len(current_output)} chars): {current_output[:100]}")

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
            except json.JSONDecodeError as exc:
                if verbose:
                    print(f"[pipeline] WARNING: Repair JSON parse failed ({exc}), falling back to text parsing")
                    print(f"[pipeline] Raw repair output ({len(current_output)} chars): {current_output[:200]}...")
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
