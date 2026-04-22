# Skill Feat Repair Narrowing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When repair passes fix skill feat prerequisite failures, rebuild the JSON schema's skill_feat enums to only include feats the character actually qualifies for (based on the build's trained skills). This eliminates the "guess from too-large pool" failure mode that causes 3/7 benchmark cases to fail.

**Architecture:** First attempt uses the broad schema (might get lucky). On repair, extract trained skills from the build JSON, use `list_skill_feats_for_skills()` to compute eligible feats, rebuild a narrowed copy of the schema with tighter skill_feat enums, and pass that to the repair LLM call. The repair prompt also gets a human-readable list of valid skill feats grouped by skill.

**Tech Stack:** No new dependencies. Uses existing `list_skill_feats_for_skills()` from static_reader and `group_skill_feats_by_skill()`.

---

## File Structure

```
mcp-pf2e/
  orchestrator/
    prompt_builder.py           # MODIFIED: add narrow_skill_feat_enums()
    pipeline.py                 # MODIFIED: repair loop extracts skills, narrows schema
  validator/
    repair.py                   # MODIFIED: format_repair_prompt accepts valid_skill_feats
```

---

### Task 1: Add `narrow_skill_feat_enums()` to prompt_builder

**Files:**
- Modify: `mcp-pf2e/orchestrator/prompt_builder.py`

Add a function that takes a response schema dict and a list of trained skills, returns a deep copy with skill_feat enums replaced by the narrowed set.

- [ ] **Step 1: Add the function**

Append to `prompt_builder.py`, after the existing functions. Import `copy` at top of file and import `list_skill_feats_for_skills` from static_reader:

```python
import copy
```

Add to the existing static_reader import line (which already imports `list_available_classes, list_available_ancestries, list_heritages, list_backgrounds`):

```python
from query.static_reader import (
    list_available_classes, list_available_ancestries, list_heritages, list_backgrounds,
    list_skill_feats_for_skills,
)
```

Then add the function:

```python
def narrow_skill_feat_enums(
    schema: dict,
    trained_skills: list[str],
    character_level: int,
) -> dict:
    """Return a copy of the response schema with skill_feat enums narrowed.

    Replaces the broad skill_feat enum at each level with only feats
    whose 'trained in X' prerequisites are met by the given skills.
    """
    narrowed = copy.deepcopy(schema)
    eligible = list_skill_feats_for_skills(trained_skills, character_level)
    eligible_names = sorted(set(f.name for f in eligible))

    levels_props = narrowed.get("properties", {}).get("levels", {}).get("properties", {})
    for level_str, level_schema in levels_props.items():
        slot_props = level_schema.get("properties", {})
        if "skill_feat" in slot_props and "enum" in slot_props["skill_feat"]:
            level_num = int(level_str)
            level_eligible = list_skill_feats_for_skills(trained_skills, level_num)
            level_names = sorted(set(f.name for f in level_eligible))
            if level_names:
                slot_props["skill_feat"]["enum"] = level_names

    return narrowed
```

- [ ] **Step 2: Verify import**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from orchestrator.prompt_builder import narrow_skill_feat_enums; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Test narrowing works**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "
from orchestrator.prompt_builder import build_response_schema, narrow_skill_feat_enums
from query.decomposer import get_build_options

opts = get_build_options('fighter', 5, 'human', [])
schema = build_response_schema(opts)

# Count broad skill feat options at level 2
broad = schema['properties']['levels']['properties']['2']['properties']['skill_feat']['enum']
print(f'Broad skill feats at level 2: {len(broad)}')

# Narrow to just Athletics + Intimidation
narrowed = narrow_skill_feat_enums(schema, ['athletics', 'intimidation'], 5)
narrow = narrowed['properties']['levels']['properties']['2']['properties']['skill_feat']['enum']
print(f'Narrowed skill feats at level 2: {len(narrow)}')
print(f'Sample: {narrow[:5]}')

# Verify original schema unchanged
broad_after = schema['properties']['levels']['properties']['2']['properties']['skill_feat']['enum']
print(f'Original still broad: {len(broad_after)}')
"`

Expected: broad ~143, narrowed much smaller (~20-30), original unchanged.

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/orchestrator/prompt_builder.py
git commit -m "feat(prompt_builder): add narrow_skill_feat_enums() for repair pass filtering"
```

---

### Task 2: Enhance repair prompt with valid skill feat list

**Files:**
- Modify: `mcp-pf2e/validator/repair.py`

Add an optional `valid_skill_feats` parameter to `format_repair_prompt()`. When provided and the errors include prerequisite failures, append a section listing valid alternatives grouped by skill.

- [ ] **Step 1: Update `format_repair_prompt` signature and add skill feat section**

Replace the full content of `repair.py`:

```python
"""Format validation errors as an LLM repair prompt."""

from .types import ValidationResult


def format_repair_prompt(
    result: ValidationResult,
    original_prompt: str = "",
    history: list[dict] | None = None,
    valid_skill_feats: dict[str, list[str]] | None = None,
) -> str:
    """Format validation errors into a repair prompt with cumulative history.

    Args:
        result: Current validation result
        original_prompt: The original build request
        history: List of previous attempts, each with:
            {"attempt": N, "errors": [{"rule": ..., "message": ..., "feat_name": ...}]}
        valid_skill_feats: Optional dict of {skill_name: [feat_names]} for narrowed replacements.
            When provided, appended as a "valid skill feats" section to guide repair.
    """
    if result.is_valid:
        return ""

    lines = []

    if original_prompt:
        lines.append(f"Original request: {original_prompt}")
        lines.append("")

    # Cumulative history — show what was already tried and failed
    if history:
        failed_names = set()
        lines.append("=== PREVIOUS FAILED ATTEMPTS ===")
        for h in history:
            lines.append(f"Attempt {h['attempt']}:")
            for err in h["errors"]:
                lines.append(f"  - {err['message']}")
                if err.get("feat_name"):
                    failed_names.add(err["feat_name"])
        lines.append("")

        if failed_names:
            lines.append(f"Do NOT use any of these (all invalid): {', '.join(sorted(failed_names))}")
            lines.append("")

    lines.append(f"Your build STILL has {result.error_count} error(s):" if history else f"Your build had {result.error_count} error(s):")
    lines.append("")

    for i, error in enumerate(result.errors, 1):
        rule_label = error.rule.upper().replace("_", " ")
        lines.append(f"{i}. [{rule_label}] {error.message}")

        if error.details.get("suggestion"):
            lines.append(f"   Suggestion: use \"{error.details['suggestion']}\" instead.")

    if result.warnings:
        lines.append("")
        lines.append("Warnings (non-blocking):")
        for w in result.warnings:
            lines.append(f"  - [{w.rule}] {w.message}")

    # Valid skill feats section — guides repair toward actually eligible choices
    if valid_skill_feats:
        has_prereq_error = any(
            e.rule == "prerequisite" for e in result.errors
        )
        if has_prereq_error:
            lines.append("")
            lines.append("=== VALID SKILL FEATS FOR YOUR TRAINED SKILLS ===")
            lines.append("Pick skill feat replacements ONLY from this list:")
            for skill_name in sorted(valid_skill_feats):
                feat_names = valid_skill_feats[skill_name]
                if feat_names:
                    lines.append(f"  {skill_name}: {', '.join(sorted(feat_names))}")

    lines.append("")
    lines.append("Fix ONLY the errors listed above. Keep all other choices the same.")
    lines.append("Output the complete corrected build as valid JSON.")

    return "\n".join(lines)
```

- [ ] **Step 2: Verify import**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from validator.repair import format_repair_prompt; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mcp-pf2e/validator/repair.py
git commit -m "feat(repair): add valid_skill_feats guidance to repair prompt"
```

---

### Task 3: Wire narrowed schema into pipeline repair loop

**Files:**
- Modify: `mcp-pf2e/orchestrator/pipeline.py`

In the repair loop, after parsing build JSON from a failed attempt, extract trained skills from the `skills` field, call `narrow_skill_feat_enums()` to build a tightened schema, and call `group_skill_feats_by_skill()` to build the valid_skill_feats dict for the repair prompt.

- [ ] **Step 1: Add imports**

Add to the imports at the top of `pipeline.py`:

```python
from orchestrator.prompt_builder import (
    build_system_prompt, build_generation_prompt, build_skeleton_prompts,
    build_skeleton_schema, build_response_schema,
    narrow_skill_feat_enums,
)
```

Also add:

```python
from query.static_reader import group_skill_feats_by_skill
```

- [ ] **Step 2: Modify the repair loop**

In the repair loop (starting around line 288 `for i in range(max_repairs):`), after the error history is recorded and before calling `_call_ollama`, add logic to:
1. Try to parse the current output as JSON to extract skills
2. If skills found, narrow the schema and build the valid_skill_feats dict
3. Pass narrowed schema to `_call_ollama` and valid_skill_feats to `format_repair_prompt`

Replace the repair loop section (from `repair_prompt = format_repair_prompt(...)` through `current_output, repair_time, repair_usage = _call_ollama(...)`) with:

```python
        # Extract trained skills from current build for narrowed repair
        repair_schema = response_schema
        valid_skill_feats = None
        try:
            current_build = json.loads(current_output)
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
```

- [ ] **Step 3: Verify import chain**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from orchestrator.pipeline import run_build; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/orchestrator/pipeline.py
git commit -m "feat(pipeline): narrow skill feat enums on repair based on build's actual trained skills"
```

---

### Task 4: Run benchmark to verify improvement

**Files:**
- No code changes. Run the same suite and compare.

- [ ] **Step 1: Run the three previously failing cases**

```bash
cd /home/labrat/projects/path2charter/mcp-pf2e
python -m benchmarks.runner --configs qwen3-schema-on --cases simple-fighter wizard-illusionist exemplar-thrown
```

- [ ] **Step 2: Compare with baseline**

```bash
python -m benchmarks.report list
python -m benchmarks.report show <new_run_id>
```

Compare pass rate: baseline was 4/7 (57%). Target: 6/7 or 7/7.

- [ ] **Step 3: If improved, run full suite for complete comparison**

```bash
python -m benchmarks.runner --configs qwen3-schema-on
python -m benchmarks.report compare <baseline_run_id> --configs qwen3-schema-on
```

---

## Self-Review

1. **Spec coverage:**
   - [x] Narrow skill feat enums on repair — Task 1 (schema) + Task 3 (pipeline wiring)
   - [x] Human-readable valid skill feat list in repair prompt — Task 2
   - [x] No extra LLM call — repair uses same `_call_ollama`, just different schema
   - [x] First attempt uses broad schema (might get lucky) — unchanged
   - [x] Original schema not mutated — `copy.deepcopy` in Task 1
   - [x] Benchmark comparison — Task 4

2. **Placeholder scan:** None found.

3. **Type consistency:**
   - `narrow_skill_feat_enums(schema, trained_skills, character_level)` → returns dict — used in pipeline.py
   - `group_skill_feats_by_skill(trained_skills, max_level)` → returns `dict[str, list[FeatOption]]` — converted to `dict[str, list[str]]` in pipeline.py
   - `format_repair_prompt(..., valid_skill_feats=dict[str, list[str]])` — consumed in pipeline.py
