# Pipeline Benchmark System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified benchmark system that runs fixed PF2e build requests through the pipeline with varying model/config combinations, evaluates quality via LLM-as-judge, and tracks results over time. Also decouple the validator from ChromaDB so benchmarks measure model performance, not DB latency.

**Architecture:** Two tracks merged into one plan. Track A adds a filesystem-based feat lookup to `static_reader` and rewires the validator to use it instead of ChromaDB. Track B creates a benchmark system in `mcp-pf2e/benchmarks/` with a static suite (cases × run_configs matrix), an LLM-as-judge evaluator, a runner that does the cross product, and a report generator reading append-only JSONL. The pipeline's `_call_ollama` is extended to return token usage.

**Tech Stack:** Python 3.11+, dataclasses, argparse, OpenAI SDK (via Ollama), JSONL for storage, no new dependencies.

---

## File Structure

```
mcp-pf2e/
  query/
    static_reader.py            # MODIFIED: add get_feat_data() for raw JSON lookup by name
  validator/
    rules.py                    # MODIFIED: replace db.get_entry() with static_reader lookups
    engine.py                   # MODIFIED: remove db parameter from BuildValidator
  orchestrator/
    pipeline.py                 # MODIFIED: _call_ollama returns tokens; run_build aggregates
  benchmarks/
    __init__.py                 # empty
    suite.json                  # static test cases + run configs (versioned)
    evaluator.py                # LLM-as-judge scoring (theme + synergy)
    runner.py                   # CLI: runs cases × configs, appends JSONL
    report.py                   # reads JSONL, prints tables + comparisons
    .gitignore                  # results.jsonl
llm-eval_dormant/               # renamed from llm-eval/
```

---

### Task 1: Add `get_feat_data()` to static_reader

**Files:**
- Modify: `mcp-pf2e/query/static_reader.py`

Build a `{name_lower: filepath}` index across all feat directories, cached. Return raw JSON dicts (same shape as `db.get_entry()`).

- [ ] **Step 1: Add the feat index builder and `get_feat_data()` function**

Append to `static_reader.py`:

```python
@lru_cache(maxsize=1)
def _build_feat_index() -> dict[str, Path]:
    """Build name→filepath index across all feat directories."""
    index = {}
    feats_root = _STATIC_ROOT / "feats"
    if not feats_root.exists():
        return index
    for filepath in feats_root.rglob("*.json"):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "name" in data:
                index[data["name"].lower()] = filepath
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return index


def get_feat_data(feat_name: str) -> dict | None:
    """Look up a feat by name and return its raw FoundryVTT JSON.

    Returns None if feat not found. This replaces db.get_entry() for
    validator rules — no ChromaDB or embedding model needed.
    """
    index = _build_feat_index()
    filepath = index.get(feat_name.lower())
    if not filepath:
        filepath = index.get(_slugify(feat_name))
    if not filepath:
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
```

- [ ] **Step 2: Verify the index finds known feats**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from query.static_reader import get_feat_data; print(get_feat_data('Power Attack') is not None); print(get_feat_data('Toughness') is not None); print(get_feat_data('Nonexistent Feat') is None)"`

Expected: `True`, `True`, `True`

- [ ] **Step 3: Commit**

```bash
git add mcp-pf2e/query/static_reader.py
git commit -m "feat(static_reader): add get_feat_data() for filesystem-based feat lookup by name"
```

---

### Task 2: Rewrite validator rules to use static_reader instead of ChromaDB

**Files:**
- Modify: `mcp-pf2e/validator/rules.py`

Replace every `db.get_entry(feat.name, content_type=None)` call with `get_feat_data(feat.name)`. Remove the `db` parameter from all rule functions. Drop semantic search fallback from `check_feat_existence` (enum constraints make it unnecessary — the LLM can only pick valid feat names).

- [ ] **Step 1: Update imports and remove db-related code**

Replace the imports and db setup at top of `rules.py`:

```python
from query.static_reader import (
    get_class_data, get_feat_slot_levels,
    get_class_trained_skills, get_background_data, get_ancestry_data,
    list_heritages, list_backgrounds, _fuzzy_match,
    get_feat_data,
)
```

Remove the `try: from server.db import PF2eDB` block entirely.

- [ ] **Step 2: Rewrite `check_feat_existence` — remove db param, use get_feat_data**

```python
def check_feat_existence(build: ParsedBuild) -> list[ValidationError]:
    """Verify every named feat exists in the static data."""
    errors = []
    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if entry:
            rarity = entry.get("system", {}).get("traits", {}).get("rarity", "common")
            if rarity in ("uncommon", "rare", "unique"):
                errors.append(ValidationError(
                    rule="rarity",
                    severity="warning",
                    message=f'"{feat.name}" is {rarity} — typically requires GM permission.',
                    feat_name=feat.name,
                    details={"rarity": rarity},
                ))
            continue
        errors.append(ValidationError(
            rule="feat_existence",
            severity="error",
            message=f'"{feat.name}" is not a known PF2e feat, spell, or feature.',
            feat_name=feat.name,
        ))
    return errors
```

- [ ] **Step 3: Rewrite `check_level_legality` — remove db param**

```python
def check_level_legality(build: ParsedBuild) -> list[ValidationError]:
    """Each feat's level must be <= the character level at which it's taken."""
    errors = []
    if build.character_level == 0:
        return errors
    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        feat_level_raw = entry.get("system", {}).get("level", {})
        if isinstance(feat_level_raw, dict):
            feat_level = feat_level_raw.get("value", 0)
        else:
            feat_level = feat_level_raw or 0
        feat_level = int(feat_level)
        check_level = feat.character_level if feat.character_level > 0 else build.character_level
        if feat_level > check_level:
            errors.append(ValidationError(
                rule="level_legality",
                severity="error",
                message=f'"{feat.name}" is level {feat_level} but taken at character level {check_level}.',
                feat_name=feat.name,
                details={"feat_level": feat_level, "character_level": check_level},
            ))
    return errors
```

- [ ] **Step 4: Rewrite `check_feat_slot_type` — remove db param**

```python
def check_feat_slot_type(build: ParsedBuild) -> list[ValidationError]:
    """Verify feats are in the correct slot type."""
    errors = []
    for feat in build.feats:
        if not feat.slot_type or feat.slot_type == "archetype":
            continue
        valid_categories = _SLOT_TO_VALID_CATEGORIES.get(feat.slot_type)
        if not valid_categories:
            continue
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        category = (entry.get("system", {}).get("category", "") or "").lower()
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]
        if feat.slot_type == "class" and "archetype" in traits_lower:
            continue
        if category and category not in valid_categories:
            errors.append(ValidationError(
                rule="feat_slot_type",
                severity="error",
                message=f'"{feat.name}" is a {category} feat, not a {feat.slot_type} feat.',
                feat_name=feat.name,
                details={"category": category, "slot_type": feat.slot_type},
            ))
    return errors
```

- [ ] **Step 5: Rewrite `check_class_feat_access` — remove db param**

```python
def check_class_feat_access(build: ParsedBuild) -> list[ValidationError]:
    """Class feats must have the character's class in their traits."""
    errors = []
    if not build.class_name:
        return errors
    class_slug = build.class_name.lower()
    for feat in build.feats:
        if feat.slot_type != "class":
            continue
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]
        if class_slug not in traits_lower and "archetype" not in traits_lower:
            errors.append(ValidationError(
                rule="class_feat_access",
                severity="error",
                message=f'"{feat.name}" is not available to {build.class_name} (traits: {traits}).',
                feat_name=feat.name,
                details={"traits": traits, "class": build.class_name},
            ))
    return errors
```

- [ ] **Step 6: Rewrite `check_ancestry_feat_access` — remove db param**

```python
def check_ancestry_feat_access(build: ParsedBuild) -> list[ValidationError]:
    """Ancestry feats must belong to the character's ancestry."""
    errors = []
    if not build.ancestry_name:
        return errors
    ancestry_slug = build.ancestry_name.lower()
    for feat in build.feats:
        if feat.slot_type != "ancestry":
            continue
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]
        if ancestry_slug not in traits_lower:
            errors.append(ValidationError(
                rule="ancestry_feat_access",
                severity="error",
                message=f'"{feat.name}" is not a {build.ancestry_name} ancestry feat (traits: {traits}).',
                feat_name=feat.name,
                details={"traits": traits, "ancestry": build.ancestry_name},
            ))
    return errors
```

- [ ] **Step 7: Rewrite `check_prerequisites` — remove db param**

```python
def check_prerequisites(build: ParsedBuild) -> list[ValidationError]:
    """Check that each feat's prerequisites are satisfied."""
    errors = []
    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        prereqs_raw = entry.get("system", {}).get("prerequisites", {}).get("value", [])
        prereq_parts = []
        for p in prereqs_raw:
            if isinstance(p, dict):
                prereq_parts.append(p.get("value", ""))
            elif isinstance(p, str):
                prereq_parts.append(p)
        prereq_string = "; ".join(p for p in prereq_parts if p)
        if not prereq_string:
            continue
        parsed = parse_prerequisites(prereq_string)
        for prereq in parsed:
            satisfied, reason = check_prerequisite(prereq, build)
            if not satisfied:
                errors.append(ValidationError(
                    rule="prerequisite",
                    severity="error",
                    message=f'"{feat.name}" {reason}.',
                    feat_name=feat.name,
                    details={"prerequisite": prereq.raw, "type": prereq.type},
                ))
    return errors
```

- [ ] **Step 8: Rewrite `check_archetype_rules` — remove db param**

```python
def check_archetype_rules(build: ParsedBuild) -> list[ValidationError]:
    """Check PF2e archetype dedication rules."""
    errors = []
    dedications = []
    archetype_feats = []
    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]
        if "dedication" in traits_lower:
            dedications.append(feat.name)
        elif "archetype" in traits_lower:
            archetype_feats.append(feat.name)
    if len(dedications) >= 2 and len(archetype_feats) < 2:
        errors.append(ValidationError(
            rule="archetype_rules",
            severity="error",
            message=f"Second dedication ({dedications[1]}) requires at least 2 non-dedication archetype feats from the first ({dedications[0]}).",
            details={"dedications": dedications, "archetype_feats": archetype_feats},
        ))
    return errors
```

- [ ] **Step 9: Commit**

```bash
git add mcp-pf2e/validator/rules.py
git commit -m "refactor(validator): replace ChromaDB lookups with static_reader get_feat_data()"
```

---

### Task 3: Update validator engine — remove db dependency

**Files:**
- Modify: `mcp-pf2e/validator/engine.py`

- [ ] **Step 1: Remove db from BuildValidator and update rule calls**

```python
"""Build validation engine — orchestrates all validation rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild, ParsedFeatChoice, ValidationResult
from .parser import parse_build
from .rules import (
    check_duplicate_feats,
    check_feat_existence,
    check_level_legality,
    check_slot_counts,
    check_feat_slot_type,
    check_class_feat_access,
    check_ancestry_feat_access,
    check_heritage,
    check_background,
    check_skill_ranks,
    check_skill_counts,
    check_ability_scores,
    check_prerequisites,
    check_archetype_rules,
)


class BuildValidator:
    """Orchestrates all validation rules for a PF2e character build."""

    def _run_rules(self, build: ParsedBuild) -> ValidationResult:
        """Run all validation rules against a parsed build."""
        all_errors = []
        all_errors.extend(check_duplicate_feats(build))
        all_errors.extend(check_feat_existence(build))
        all_errors.extend(check_level_legality(build))
        all_errors.extend(check_slot_counts(build))
        all_errors.extend(check_feat_slot_type(build))
        all_errors.extend(check_class_feat_access(build))
        all_errors.extend(check_ancestry_feat_access(build))
        all_errors.extend(check_heritage(build))
        all_errors.extend(check_background(build))
        all_errors.extend(check_skill_ranks(build))
        all_errors.extend(check_skill_counts(build))
        all_errors.extend(check_ability_scores(build))
        all_errors.extend(check_prerequisites(build))
        all_errors.extend(check_archetype_rules(build))

        errors = [e for e in all_errors if e.severity == "error"]
        warnings = [e for e in all_errors if e.severity == "warning"]

        errored_feats = {e.feat_name for e in errors if e.feat_name}
        verified = [f.name for f in build.feats if f.name not in errored_feats]

        return ValidationResult(
            errors=errors,
            warnings=warnings,
            verified_feats=verified,
            build=build,
        )

    def validate(
        self,
        text: str,
        expected_class: str = "",
        expected_ancestry: str = "",
        expected_level: int = 0,
    ) -> ValidationResult:
        """Validate a free-text (markdown) build via regex parsing."""
        build = parse_build(
            text,
            expected_class=expected_class,
            expected_ancestry=expected_ancestry,
            expected_level=expected_level,
        )
        return self._run_rules(build)

    def validate_json(
        self,
        data: dict,
        expected_class: str = "",
        expected_ancestry: str = "",
        expected_level: int = 0,
    ) -> ValidationResult:
        """Validate a JSON build directly — no regex parsing."""
        build = ParsedBuild(
            class_name=data.get("class", expected_class).lower(),
            ancestry_name=data.get("ancestry", expected_ancestry).lower(),
            heritage=data.get("heritage", ""),
            background=data.get("background", ""),
            character_level=data.get("level", expected_level),
            ability_scores=data.get("ability_scores", {}),
            skills=data.get("skills", {}),
            equipment=data.get("equipment", []),
            raw_text="",
        )

        feats = []
        levels_data = data.get("levels", {})
        for level_str, slots in levels_data.items():
            try:
                level_num = int(level_str)
            except (ValueError, TypeError):
                continue
            if not isinstance(slots, dict):
                continue
            for slot_key, feat_name in slots.items():
                if not feat_name or not isinstance(feat_name, str):
                    continue
                slot_type = slot_key.replace("_feat", "")
                feats.append(ParsedFeatChoice(
                    name=feat_name,
                    slot_type=slot_type,
                    character_level=level_num,
                ))
        build.feats = feats

        return self._run_rules(build)
```

- [ ] **Step 2: Update `run_build()` in pipeline.py to use the new validator (no db)**

In `pipeline.py`, replace the validator setup block (~lines 247-253):

Old:
```python
    try:
        from server.db import PF2eDB
        db = PF2eDB()
    except Exception:
        db = None

    validator = BuildValidator(db=db, skip_semantic=skip_semantic)
```

New:
```python
    validator = BuildValidator()
```

Also remove the `skip_semantic` parameter from `run_build()` since it's no longer used.

- [ ] **Step 3: Verify the validator still works on an existing build**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "
from validator.engine import BuildValidator
import json
with open('builds/goblin_thaumaturge_lvl4.json') as f:
    data = json.load(f)
v = BuildValidator()
result = v.validate_json(data['build_json'], 'thaumaturge', 'goblin', 4)
print(result.summary())
"`

Expected: `VALID` with verified feats.

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/validator/engine.py mcp-pf2e/orchestrator/pipeline.py
git commit -m "refactor(validator): remove ChromaDB dependency, use filesystem-only validation"
```

---

### Task 4: Extend `_call_ollama` to return token usage

**Files:**
- Modify: `mcp-pf2e/orchestrator/pipeline.py`

- [ ] **Step 1: Update `_call_ollama` return type**

Change return from `tuple[str, float]` to `tuple[str, float, dict]`:

```python
def _call_ollama(
    model: str,
    prompt: str,
    system_prompt: str,
    temperature: float = 0.7,
    json_mode: bool = True,
    response_schema: dict | None = None,
    max_tokens: int = 2048,
) -> tuple[str, float, dict]:
    """Call Ollama via OpenAI-compatible API. Returns (content, elapsed_seconds, token_usage)."""
    # ... existing code until response = ...

    content = response.choices[0].message.content or ""
    usage = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return content, round(elapsed, 2), usage
```

- [ ] **Step 2: Update all call sites in `run_build()`**

Add `all_usages = []` after `timings = {}`. Update each `_call_ollama` call to unpack 3 values and append usage:

Skeleton: `skeleton_raw, skeleton_time, skeleton_usage = _call_ollama(...)` + `all_usages.append(skeleton_usage)`
Generate: `raw_output, gen_time, gen_usage = _call_ollama(...)` + `all_usages.append(gen_usage)`
Repair: `current_output, repair_time, repair_usage = _call_ollama(...)` + `all_usages.append(repair_usage)`

After result dict, aggregate:
```python
    token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in all_usages:
        for k in token_totals:
            token_totals[k] += u.get(k, 0)
    result["tokens"] = token_totals
```

- [ ] **Step 3: Verify import still works**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from orchestrator.pipeline import run_build, _call_ollama; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/orchestrator/pipeline.py
git commit -m "feat(pipeline): return token usage from _call_ollama, aggregate in run_build"
```

---

### Task 5: Create benchmark suite file

**Files:**
- Create: `mcp-pf2e/benchmarks/__init__.py`
- Create: `mcp-pf2e/benchmarks/suite.json`
- Create: `mcp-pf2e/benchmarks/.gitignore`

- [ ] **Step 1: Create files**

`__init__.py`: empty

`suite.json`:
```json
{
  "version": "1.0",
  "cases": [
    {
      "id": "simple-fighter",
      "label": "Basic melee fighter",
      "request": "A straightforward melee fighter who hits hard",
      "class": "fighter",
      "ancestry": "human",
      "level": 5,
      "dedications": [],
      "expect_themes": ["melee", "strength", "martial weapons"],
      "difficulty": "easy"
    },
    {
      "id": "thrown-fighter",
      "label": "Thrown weapon fighter (regression)",
      "request": "A fighter specializing in thrown weapons",
      "class": "fighter",
      "ancestry": "human",
      "level": 3,
      "dedications": [],
      "expect_themes": ["thrown", "ranged", "javelin"],
      "difficulty": "easy"
    },
    {
      "id": "thaum-champion",
      "label": "Thaumaturge with Champion dedication",
      "request": "A goblin hustler who dabbles in divine protection",
      "class": "thaumaturge",
      "ancestry": "goblin",
      "level": 4,
      "dedications": ["champion"],
      "expect_themes": ["divine", "protection", "esoterica"],
      "difficulty": "medium"
    },
    {
      "id": "sneaky-caster",
      "label": "Concept-only: no class specified",
      "request": "A character who casts spells up close while staying hidden",
      "class": null,
      "ancestry": null,
      "level": null,
      "dedications": null,
      "expect_themes": ["stealth", "melee spells", "illusion"],
      "difficulty": "hard"
    },
    {
      "id": "wizard-illusionist",
      "label": "Illusion-focused wizard",
      "request": "Wizard with a spellbook favoring illusion magic",
      "class": "wizard",
      "ancestry": null,
      "level": 7,
      "dedications": [],
      "expect_themes": ["illusion", "deception", "spellbook"],
      "difficulty": "medium"
    },
    {
      "id": "exemplar-thrown",
      "label": "Exemplar thrown + defensive",
      "request": "Exemplar favoring thrown weapons and defensive abilities",
      "class": "exemplar",
      "ancestry": null,
      "level": 8,
      "dedications": [],
      "expect_themes": ["thrown", "defense", "ikon"],
      "difficulty": "medium"
    },
    {
      "id": "complex-multiclass",
      "label": "Complex multiclass build",
      "request": "A dwarven inventor who also practices medicine on the battlefield",
      "class": "inventor",
      "ancestry": "dwarf",
      "level": 6,
      "dedications": ["medic"],
      "expect_themes": ["crafting", "healing", "innovation"],
      "difficulty": "hard"
    }
  ],
  "run_configs": [
    {
      "id": "qwen3-schema-on",
      "model": "ollama-qwen3-32b",
      "judge_model": "mistral-small3.2:24b",
      "schema_enforced": true,
      "temperature": 0.5,
      "max_repairs": 2,
      "use_vector_ranking": false,
      "notes": "Qwen3 32B thinking model, schema enforced"
    },
    {
      "id": "qwen25-schema-on",
      "model": "ollama-qwen32b",
      "judge_model": "mistral-small3.2:24b",
      "schema_enforced": true,
      "temperature": 0.5,
      "max_repairs": 2,
      "use_vector_ranking": false,
      "notes": "Qwen2.5 32B non-thinking, schema enforced"
    },
    {
      "id": "qwen3-with-ranking",
      "model": "ollama-qwen3-32b",
      "judge_model": "mistral-small3.2:24b",
      "schema_enforced": true,
      "temperature": 0.5,
      "max_repairs": 2,
      "use_vector_ranking": true,
      "notes": "Qwen3 + vector DB feat ranking (future)"
    }
  ]
}
```

`.gitignore`:
```
results.jsonl
```

- [ ] **Step 2: Commit**

```bash
git add mcp-pf2e/benchmarks/__init__.py mcp-pf2e/benchmarks/suite.json mcp-pf2e/benchmarks/.gitignore
git commit -m "feat(benchmarks): add test suite with 7 cases and 2 run configs"
```

---

### Task 6: Create the evaluator (LLM-as-judge)

**Files:**
- Create: `mcp-pf2e/benchmarks/evaluator.py`

- [ ] **Step 1: Create `evaluator.py`**

```python
"""LLM-as-judge evaluator for PF2e character builds."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.pipeline import _call_ollama

EVAL_PROMPT = """\
You are evaluating a Pathfinder 2nd Edition character build for quality.

Build request: "{request}"
Expected themes: {themes}

Generated build:
{build_json}

Validation result: {validation_summary}

Score on two dimensions (1-10 each):

THEME (does the build match the requested concept?):
- 9-10: Every choice serves the concept
- 7-8: Most choices fit, minor misses
- 5-6: Mixed, some choices seem random
- 3-4: Weak connection to concept
- 1-2: Build ignores the concept

SYNERGY (do the choices work together mechanically?):
- 9-10: Choices create strong combos and action economy
- 7-8: Solid choices, no wasted picks
- 5-6: Some choices don't contribute to the build
- 3-4: Contradictory or redundant picks
- 1-2: Random selection with no coherent strategy

Return ONLY this JSON, no other text:
{{"theme_score": <int 1-10>, "synergy_score": <int 1-10>, "overall_score": <number 1-10>, "notes": "<2-3 sentences explaining scores>"}}"""

EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "theme_score": {"type": "integer"},
        "synergy_score": {"type": "integer"},
        "overall_score": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["theme_score", "synergy_score", "overall_score", "notes"],
}


def evaluate_build(
    request: str,
    expect_themes: list[str],
    build_json: dict | None,
    build_text: str,
    validation: dict,
    judge_model: str,
) -> dict:
    """Score a build using an LLM judge. Returns dict with scores and notes."""
    build_display = json.dumps(build_json, indent=2) if build_json else build_text

    valid_str = "VALID" if validation.get("is_valid") else "INVALID"
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])
    validation_summary = f"{valid_str}, {len(errors)} errors, {len(warnings)} warnings"
    if errors:
        validation_summary += "\nErrors: " + "; ".join(
            e["message"] if isinstance(e, dict) else str(e) for e in errors[:5]
        )

    prompt = EVAL_PROMPT.format(
        request=request,
        themes=", ".join(expect_themes),
        build_json=build_display,
        validation_summary=validation_summary,
    )

    content, elapsed, usage = _call_ollama(
        model=judge_model,
        prompt=prompt,
        system_prompt="You are a PF2e rules expert scoring character builds. Return only valid JSON.",
        temperature=0.2,
        json_mode=False,
        response_schema=EVAL_SCHEMA,
        max_tokens=512,
    )

    try:
        scores = json.loads(content)
    except json.JSONDecodeError:
        scores = {
            "theme_score": 0,
            "synergy_score": 0,
            "overall_score": 0,
            "notes": f"Judge parse error: {content[:200]}",
        }

    return {
        "theme_score": scores.get("theme_score", 0),
        "synergy_score": scores.get("synergy_score", 0),
        "overall_score": scores.get("overall_score", 0),
        "evaluator_notes": scores.get("notes", ""),
        "judge_time": elapsed,
        "judge_tokens": usage,
    }
```

- [ ] **Step 2: Verify import**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from benchmarks.evaluator import evaluate_build; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mcp-pf2e/benchmarks/evaluator.py
git commit -m "feat(benchmarks): add LLM-as-judge evaluator for theme and synergy scoring"
```

---

### Task 7: Create the benchmark runner

**Files:**
- Create: `mcp-pf2e/benchmarks/runner.py`

The runner loads the suite, does the cases × configs cross product (or a filtered subset), calls `run_build()` for each, evaluates with the judge, and appends JSONL. Flags unsupported config parameters in output.

- [ ] **Step 1: Create `runner.py`**

```python
"""Benchmark runner — cases x configs matrix through the pipeline."""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.pipeline import run_build, LOCAL_MODELS, THINKING_MODELS, _unload_all_models
from benchmarks.evaluator import evaluate_build

SUITE_PATH = Path(__file__).parent / "suite.json"
RESULTS_PATH = Path(__file__).parent / "results.jsonl"

SUPPORTED_CONFIG_KEYS = {
    "id", "model", "judge_model", "schema_enforced", "temperature", "max_repairs", "notes",
}


def load_suite(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def flag_unsupported(config: dict) -> list[str]:
    """Return list of config keys not yet supported by the pipeline."""
    flags = []
    for key, value in config.items():
        if key not in SUPPORTED_CONFIG_KEYS and value not in (False, None, "", 0):
            flags.append(f"{key}={value}")
    return flags


def next_run_id(results_path: Path) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    seq = 1
    if results_path.exists():
        with open(results_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    rid = entry.get("run_id", "")
                    if rid.startswith(today):
                        num = int(rid.split("_")[-1])
                        seq = max(seq, num + 1)
                except (json.JSONDecodeError, ValueError):
                    continue
    return f"{today}_{seq:03d}"


def run_case(case: dict, config: dict, unsupported: list[str]) -> dict:
    """Run a single benchmark case with a given config."""
    print(f"\n{'='*60}")
    print(f"  Case: {case['id']} — {case['label']}")
    print(f"  Config: {config['id']} ({config['model']})")
    if unsupported:
        print(f"  ⚠ Unsupported config (ignored): {', '.join(unsupported)}")
    print(f"{'='*60}")

    output_format = "json" if config.get("schema_enforced", True) else "markdown"

    result = run_build(
        request=case["request"],
        class_name=case.get("class") or "",
        character_level=case.get("level") or 0,
        ancestry_name=case.get("ancestry") or "",
        dedications=case.get("dedications") or [],
        provider_key=config["model"],
        max_repairs=config.get("max_repairs", 2),
        temperature=config.get("temperature", 0.7),
        output_format=output_format,
        verbose=True,
    )

    if "error" in result:
        print(f"  PIPELINE ERROR: {result['error']}")
        return {
            "valid": False,
            "attempts": 0,
            "timings": result.get("timings", {}),
            "tokens": result.get("tokens", {}),
            "theme_score": 0,
            "synergy_score": 0,
            "overall_score": 0,
            "evaluator_notes": f"Pipeline error: {result['error']}",
            "judge_time": 0,
            "judge_tokens": {},
            "errors": [],
            "warnings": [],
            "skeleton": result.get("skeleton"),
        }

    print(f"\n[benchmark] Unloading generator, loading judge...")
    _unload_all_models()

    scores = evaluate_build(
        request=case["request"],
        expect_themes=case.get("expect_themes", []),
        build_json=result.get("build_json"),
        build_text=result.get("build_text", ""),
        validation=result.get("validation", {}),
        judge_model=config["judge_model"],
    )

    validation = result.get("validation", {})
    return {
        "valid": validation.get("is_valid", False),
        "attempts": result.get("attempts", 1),
        "timings": result.get("timings", {}),
        "tokens": result.get("tokens", {}),
        "theme_score": scores["theme_score"],
        "synergy_score": scores["synergy_score"],
        "overall_score": scores["overall_score"],
        "evaluator_notes": scores["evaluator_notes"],
        "judge_time": scores.get("judge_time", 0),
        "judge_tokens": scores.get("judge_tokens", {}),
        "errors": [e["message"] for e in validation.get("errors", [])],
        "warnings": [w["message"] for w in validation.get("warnings", [])],
        "skeleton": result.get("skeleton"),
    }


def run_benchmark(
    suite_path: Path,
    results_path: Path,
    config_filter: list[str] | None = None,
    case_filter: list[str] | None = None,
    runs_per_case: int = 1,
):
    """Run the full cases x configs matrix."""
    suite = load_suite(suite_path)
    cases = suite["cases"]
    configs = suite.get("run_configs", [])

    if case_filter:
        cases = [c for c in cases if c["id"] in case_filter]
    if config_filter:
        configs = [c for c in configs if c["id"] in config_filter]

    if not cases:
        print("No cases matched filter.")
        return
    if not configs:
        print("No configs matched filter.")
        return

    run_id = next_run_id(results_path)

    print(f"Benchmark run: {run_id}")
    print(f"Suite: {suite_path.name} v{suite.get('version', '?')}")
    print(f"Matrix: {len(cases)} cases × {len(configs)} configs × {runs_per_case} runs = {len(cases) * len(configs) * runs_per_case} total")
    print(f"Results: {results_path}")
    print()

    for config in configs:
        unsupported = flag_unsupported(config)
        model_is_thinking = config["model"] in THINKING_MODELS

        print(f"\n{'#'*60}")
        print(f"  Config: {config['id']}")
        print(f"  Model: {config['model']} (thinking={model_is_thinking})")
        print(f"  Judge: {config['judge_model']}")
        if unsupported:
            print(f"  ⚠ Unsupported parameters (will be ignored): {', '.join(unsupported)}")
        if config.get("notes"):
            print(f"  Notes: {config['notes']}")
        print(f"{'#'*60}")

        for case in cases:
            for run_num in range(runs_per_case):
                t0 = time.time()
                case_result = run_case(case, config, unsupported)
                wall_time = round(time.time() - t0, 2)

                entry = {
                    "run_id": run_id,
                    "config_id": config["id"],
                    "case_id": case["id"],
                    "run_num": run_num + 1,
                    "timestamp": datetime.now().isoformat(),
                    "model": config["model"],
                    "model_is_thinking": model_is_thinking,
                    "judge_model": config["judge_model"],
                    "schema_enforced": config.get("schema_enforced", True),
                    "temperature": config.get("temperature", 0.7),
                    "max_repairs": config.get("max_repairs", 2),
                    "suite_version": suite.get("version", "?"),
                    "difficulty": case.get("difficulty", "?"),
                    "wall_time": wall_time,
                    "valid": case_result["valid"],
                    "attempts": case_result["attempts"],
                    "timings": case_result["timings"],
                    "tokens": case_result["tokens"],
                    "theme_score": case_result["theme_score"],
                    "synergy_score": case_result["synergy_score"],
                    "overall_score": case_result["overall_score"],
                    "evaluator_notes": case_result["evaluator_notes"],
                    "judge_time": case_result.get("judge_time", 0),
                    "judge_tokens": case_result.get("judge_tokens", {}),
                    "errors": case_result["errors"],
                    "warnings": case_result["warnings"],
                    "unsupported_config": unsupported,
                    "human_feedback": "",
                }

                with open(results_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")

                status = "VALID" if case_result["valid"] else "INVALID"
                print(f"\n  >> {status} | Theme: {case_result['theme_score']} | "
                      f"Synergy: {case_result['synergy_score']} | "
                      f"Overall: {case_result['overall_score']}")

                _unload_all_models()

    print(f"\n{'='*60}")
    print(f"Benchmark {run_id} complete. {len(cases) * len(configs) * runs_per_case} results → {results_path}")


def main():
    parser = argparse.ArgumentParser(description="Run PF2e pipeline benchmarks (cases × configs)")
    parser.add_argument("--suite", type=Path, default=SUITE_PATH,
                        help=f"Suite JSON path (default: {SUITE_PATH})")
    parser.add_argument("--results", type=Path, default=RESULTS_PATH,
                        help=f"Results JSONL path (default: {RESULTS_PATH})")
    parser.add_argument("--configs", nargs="*",
                        help="Filter to specific config IDs")
    parser.add_argument("--cases", nargs="*",
                        help="Filter to specific case IDs")
    parser.add_argument("--runs-per-case", type=int, default=1,
                        help="Runs per case for variance (default: 1)")
    args = parser.parse_args()

    run_benchmark(
        suite_path=args.suite,
        results_path=args.results,
        config_filter=args.configs,
        case_filter=args.cases,
        runs_per_case=args.runs_per_case,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI help**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -m benchmarks.runner --help`

Expected: shows `--suite`, `--results`, `--configs`, `--cases`, `--runs-per-case`

- [ ] **Step 3: Commit**

```bash
git add mcp-pf2e/benchmarks/runner.py
git commit -m "feat(benchmarks): add runner with cases × configs matrix, unsupported param flagging"
```

---

### Task 8: Create the report generator

**Files:**
- Create: `mcp-pf2e/benchmarks/report.py`

- [ ] **Step 1: Create `report.py`**

```python
"""Benchmark report — reads JSONL results, prints tables and comparisons."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / "results.jsonl"


def load_results(path: Path) -> list[dict]:
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def cmd_list(results: list[dict]):
    """List all benchmark runs."""
    runs = defaultdict(list)
    for r in results:
        runs[r["run_id"]].append(r)

    print(f"{'Run ID':<20} {'Configs':<30} {'Cases':>5} {'Avg':>6}")
    print("-" * 65)
    for run_id in sorted(runs):
        entries = runs[run_id]
        configs = sorted(set(e.get("config_id", "?") for e in entries))
        avg = sum(e.get("overall_score", 0) for e in entries) / max(len(entries), 1)
        print(f"{run_id:<20} {', '.join(configs):<30} {len(entries):>5} {avg:>6.1f}")


def cmd_show(results: list[dict], run_id: str, config_id: str | None = None):
    """Show detailed results for a run, optionally filtered by config."""
    entries = [r for r in results if r["run_id"] == run_id]
    if config_id:
        entries = [r for r in entries if r.get("config_id") == config_id]
    if not entries:
        print(f"No results for run_id={run_id}" + (f", config={config_id}" if config_id else ""))
        return

    by_config = defaultdict(list)
    for e in entries:
        by_config[e.get("config_id", "?")].append(e)

    for cid in sorted(by_config):
        c_entries = by_config[cid]
        first = c_entries[0]
        thinking = "yes" if first.get("model_is_thinking") else "no"
        print(f"\nConfig: {cid} | Model: {first['model']} (thinking={thinking}) | Judge: {first.get('judge_model', '?')}")

        unsupported = first.get("unsupported_config", [])
        if unsupported:
            print(f"⚠ Unsupported config params (ignored): {', '.join(unsupported)}")

        header = f"  {'Case':<25} {'Ok':>2} {'Att':>3} {'Time':>6} {'Thm':>4} {'Syn':>4} {'Scr':>5} {'Tok':>7}"
        print(header)
        print("  " + "-" * (len(header) - 2))

        totals = {"time": 0, "tokens": 0, "theme": 0, "synergy": 0, "overall": 0, "valid": 0}
        for e in c_entries:
            v = "Y" if e.get("valid") else "N"
            att = e.get("attempts", 0)
            wall = e.get("wall_time", 0)
            thm = e.get("theme_score", 0)
            syn = e.get("synergy_score", 0)
            scr = e.get("overall_score", 0)
            tok = e.get("tokens", {}).get("total_tokens", 0)
            print(f"  {e['case_id']:<25} {v:>2} {att:>3} {wall:>5.0f}s {thm:>4} {syn:>4} {scr:>5.1f} {tok:>7}")
            totals["time"] += wall
            totals["tokens"] += tok
            totals["theme"] += thm
            totals["synergy"] += syn
            totals["overall"] += scr
            if e.get("valid"):
                totals["valid"] += 1

        n = len(c_entries)
        print("  " + "-" * (len(header) - 2))
        print(f"  {'Avg':<25} {totals['valid']}/{n:>1} {'':>3} {totals['time']/n:>5.0f}s "
              f"{totals['theme']/n:>4.1f} {totals['synergy']/n:>4.1f} {totals['overall']/n:>5.1f} {totals['tokens']/n:>7.0f}")

        print(f"\n  Notes:")
        for e in c_entries:
            notes = e.get("evaluator_notes", "")
            if notes:
                print(f"    {e['case_id']}: {notes}")


def cmd_compare(results: list[dict], run_id: str, config_ids: list[str] | None = None):
    """Compare configs within a run (or across runs)."""
    entries = [r for r in results if r["run_id"] == run_id]
    if not entries:
        print(f"No results for run_id={run_id}")
        return

    by_config = defaultdict(dict)
    for e in entries:
        cid = e.get("config_id", "?")
        if config_ids and cid not in config_ids:
            continue
        by_config[cid][e["case_id"]] = e

    if len(by_config) < 2:
        print("Need at least 2 configs to compare.")
        return

    config_list = sorted(by_config.keys())
    all_cases = sorted(set(cid for by_case in by_config.values() for cid in by_case))

    col_w = 12
    header = f"{'Case':<25}"
    for c in config_list:
        header += f" {c:>{col_w}}"
    print(header)
    print("-" * len(header))

    for case_id in all_cases:
        line = f"{case_id:<25}"
        for c in config_list:
            entry = by_config[c].get(case_id)
            if entry:
                score = entry.get("overall_score", 0)
                line += f" {score:>{col_w}.1f}"
            else:
                line += f" {'—':>{col_w}}"
        print(line)

    print("-" * len(header))
    avg_line = f"{'Average':<25}"
    time_line = f"{'Avg time':<25}"
    token_line = f"{'Avg tokens':<25}"
    for c in config_list:
        vals = list(by_config[c].values())
        avg = sum(e.get("overall_score", 0) for e in vals) / max(len(vals), 1)
        avg_t = sum(e.get("wall_time", 0) for e in vals) / max(len(vals), 1)
        avg_tok = sum(e.get("tokens", {}).get("total_tokens", 0) for e in vals) / max(len(vals), 1)
        avg_line += f" {avg:>{col_w}.1f}"
        time_line += f" {avg_t:>{col_w}.0f}s"
        token_line += f" {avg_tok:>{col_w}.0f}"
    print(avg_line)
    print(time_line)
    print(token_line)


def main():
    parser = argparse.ArgumentParser(description="View benchmark results")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all runs")

    show_p = sub.add_parser("show", help="Show run details")
    show_p.add_argument("run_id")
    show_p.add_argument("--config", help="Filter to one config")

    cmp_p = sub.add_parser("compare", help="Compare configs within a run")
    cmp_p.add_argument("run_id")
    cmp_p.add_argument("--configs", nargs="*", help="Config IDs to compare (default: all)")

    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return
    if not args.results.exists():
        print(f"No results at {args.results}")
        return

    results = load_results(args.results)

    if args.command == "list":
        cmd_list(results)
    elif args.command == "show":
        cmd_show(results, args.run_id, getattr(args, "config", None))
    elif args.command == "compare":
        cmd_compare(results, args.run_id, getattr(args, "configs", None))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI help**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -m benchmarks.report --help`

Expected: shows `list`, `show`, `compare` subcommands

- [ ] **Step 3: Commit**

```bash
git add mcp-pf2e/benchmarks/report.py
git commit -m "feat(benchmarks): add report generator with run details and config comparison"
```

---

### Task 9: Rename llm-eval to dormant, integration test

**Files:**
- Rename: `llm-eval/` → `llm-eval_dormant/`

- [ ] **Step 1: Rename via git**

```bash
git mv llm-eval llm-eval_dormant
```

- [ ] **Step 2: Run import checks on all new modules**

```bash
cd /home/labrat/projects/path2charter/mcp-pf2e
python -c "from query.static_reader import get_feat_data; print('static_reader OK')"
python -c "from validator.engine import BuildValidator; print('validator OK')"
python -c "from orchestrator.pipeline import run_build; print('pipeline OK')"
python -c "from benchmarks.evaluator import evaluate_build; print('evaluator OK')"
python -c "from benchmarks.runner import load_suite, run_benchmark; print('runner OK')"
python -c "from benchmarks.report import load_results; print('report OK')"
```

- [ ] **Step 3: Validate an existing build with the new db-free validator**

```bash
cd /home/labrat/projects/path2charter/mcp-pf2e
python -c "
from validator.engine import BuildValidator
import json
for f in ['builds/goblin_thaumaturge_lvl4.json', 'builds/elf_ranger_lvl6.json']:
    with open(f) as fh:
        data = json.load(fh)
    bj = data.get('build_json', {})
    v = BuildValidator()
    r = v.validate_json(bj, bj.get('class','').lower(), bj.get('ancestry','').lower(), bj.get('level',0))
    print(f'{f}: {r.summary()[:80]}')
"
```

- [ ] **Step 4: Test benchmark CLI help and report help**

```bash
python -m benchmarks.runner --help
python -m benchmarks.report --help
```

- [ ] **Step 5: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: unified benchmark system, validator decoupled from ChromaDB, llm-eval dormant"
```

---

## Self-Review

1. **Spec coverage:**
   - [x] Track A: validator decoupled from ChromaDB — Tasks 1-3
   - [x] Single benchmark system in mcp-pf2e/benchmarks/ — Tasks 5-8
   - [x] Cases × configs matrix — Task 7 runner
   - [x] Unsupported config params flagged in output — Task 7 runner `flag_unsupported()`
   - [x] Token tracking — Task 4
   - [x] `model_is_thinking` boolean — Task 7 runner
   - [x] LLM-as-judge with separate judge model — Task 6
   - [x] Append-only JSONL — Task 7
   - [x] Comparison reports — Task 8
   - [x] llm-eval renamed to dormant — Task 9

2. **Placeholder scan:** None found.

3. **Type consistency:**
   - `get_feat_data()` returns `dict | None` — same shape as `db.get_entry()` — used consistently in rewritten rules
   - `_call_ollama` returns `tuple[str, float, dict]` — used in pipeline.py and evaluator.py
   - `evaluate_build()` returns dict consumed by runner
   - `BuildValidator()` takes no args — used in pipeline and standalone
