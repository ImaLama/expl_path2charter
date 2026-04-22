# Vector DB Feat Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use ChromaDB semantic search to rank each slot's valid feats by relevance to the build concept, then present top-N feats with full descriptions in the generation prompt. This guides the model toward thematically appropriate picks without changing the enum constraints (model can still pick any valid feat).

**Architecture:** New `feat_ranker.py` queries ChromaDB with the build concept, post-filters to each slot's valid feat names, and returns ranked lists. The prompt builder shows top-N feats with descriptions (from `get_feat_data()`), rest as names only. Prerequisite chain members are always included even if they didn't rank individually.

**Phased approach:**
- **Phase 1 (this plan):** Curated feat ranking per slot. Benchmark wizard-illusionist + exemplar-thrown.
- **Phase 2 (future):** Cross-collection search to inform skeleton pass class/ancestry choice.
- **Phase 3 (future):** Prerequisite dependency chain analysis — present feat paths, not isolated picks.

**Tech Stack:** ChromaDB via existing `PF2eDB` wrapper, `mxbai-embed-large` embeddings, existing `get_feat_data()` for descriptions.

---

## File Structure

```
mcp-pf2e/
  query/
    feat_ranker.py              # NEW: rank feats by concept relevance via ChromaDB
  orchestrator/
    prompt_builder.py           # MODIFIED: accept ranked feats, show top-N with descriptions
    pipeline.py                 # MODIFIED: call ranker when use_vector_ranking=True
  benchmarks/
    suite.json                  # MODIFIED: add mistral-with-ranking config
    runner.py                   # MODIFIED: add use_vector_ranking to SUPPORTED_CONFIG_KEYS
```

---

### Task 1: Create `feat_ranker.py`

**Files:**
- Create: `mcp-pf2e/query/feat_ranker.py`

The ranker takes a concept string and a `BuildOptions` object, queries ChromaDB for each slot type, and returns ranked feat names per slot. It post-filters to only feats in the slot's enum (ChromaDB doesn't support `$in` on name field).

- [ ] **Step 1: Create the ranker module**

```python
"""Rank feat options by semantic relevance to a build concept via ChromaDB."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from query.types import BuildOptions
from query.static_reader import get_feat_data

try:
    from server.db import PF2eDB
except ImportError:
    PF2eDB = None


def rank_feats_for_concept(
    concept: str,
    options: BuildOptions,
    db: "PF2eDB",
    top_class: int = 10,
    top_other: int = 5,
) -> dict[str, list[dict]]:
    """Rank each slot's feats by relevance to the build concept.

    Returns dict keyed by "{level}_{slot_type}" with lists of
    {"name": str, "score": float, "description": str} ordered by relevance.
    Only top-N are marked for description display.

    Prerequisite chain members of ranked feats are always included
    even if they didn't rank individually.
    """
    ranked_slots = {}

    # Group slots by type to batch queries (one query per type, not per slot)
    slots_by_type: dict[str, list] = {}
    for so in options.slot_options:
        slots_by_type.setdefault(so.slot.slot_type, []).append(so)

    for slot_type, slot_list in slots_by_type.items():
        # Collect all unique feat names across all levels for this type
        all_names = set()
        for so in slot_list:
            all_names.update(o.name for o in so.options)

        if not all_names:
            continue

        # Query ChromaDB — fetch more than we need, post-filter to valid names
        top_n = top_class if slot_type == "class" else top_other
        results = db.search(
            query=concept,
            content_type="feat",
            n_results=min(len(all_names), 200),
        )

        # Build relevance map from results, filtered to valid names
        relevance = {}
        for r in results:
            if r["name"] in all_names:
                relevance[r["name"]] = r["relevance_score"]

        # Find prerequisite chain members for top-ranked feats
        prereq_names = set()
        top_ranked = sorted(relevance, key=lambda n: relevance[n], reverse=True)[:top_n * 2]
        for feat_name in top_ranked:
            entry = get_feat_data(feat_name)
            if not entry:
                continue
            prereqs_raw = entry.get("system", {}).get("prerequisites", {}).get("value", [])
            for p in prereqs_raw:
                pval = p.get("value", "") if isinstance(p, dict) else str(p)
                # Check if any valid feat name appears in the prerequisite text
                for candidate in all_names:
                    if candidate.lower() in pval.lower():
                        prereq_names.add(candidate)

        # Per-slot ranking
        for so in slot_list:
            slot_names = {o.name for o in so.options}
            slot_key = f"{so.slot.level}_{so.slot.slot_type}"

            ranked = []
            for name in sorted(slot_names):
                score = relevance.get(name, 0.0)
                ranked.append({"name": name, "score": score})

            ranked.sort(key=lambda x: x["score"], reverse=True)

            # Mark top-N + prereq chain members for description display
            for i, entry in enumerate(ranked):
                show_desc = i < top_n or entry["name"] in prereq_names
                if show_desc:
                    feat_data = get_feat_data(entry["name"])
                    if feat_data:
                        desc = feat_data.get("system", {}).get("description", {}).get("value", "")
                        # Strip HTML, truncate
                        desc = desc.replace("<p>", "").replace("</p>", " ").strip()
                        if len(desc) > 200:
                            desc = desc[:200] + "..."
                        entry["description"] = desc
                entry["show_description"] = show_desc

            ranked_slots[slot_key] = ranked

    return ranked_slots
```

- [ ] **Step 2: Verify import**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from query.feat_ranker import rank_feats_for_concept; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Test with a real query (requires mxbai loaded in Ollama)**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "
from query.feat_ranker import rank_feats_for_concept
from query.decomposer import get_build_options
from server.db import PF2eDB

db = PF2eDB()
opts = get_build_options('fighter', 5, 'human', [])
ranked = rank_feats_for_concept('thrown weapons specialist', opts, db)
for key in sorted(ranked)[:3]:
    entries = ranked[key]
    top3 = [e for e in entries if e.get('show_description')][:3]
    print(f'{key}: top={[e[\"name\"] for e in top3]}')
"`

Expected: thrown-weapon-relevant feats ranked higher.

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/query/feat_ranker.py
git commit -m "feat(query): add feat_ranker for concept-to-feat relevance ranking via ChromaDB"
```

---

### Task 2: Modify prompt builder to use ranked feats

**Files:**
- Modify: `mcp-pf2e/orchestrator/prompt_builder.py`

Update `build_generation_prompt()` to accept optional ranked feats. When provided, restructure the feat listing: show ranked feats with descriptions first, then remaining as names only.

- [ ] **Step 1: Update `build_generation_prompt` signature and slot rendering**

Add `ranked_feats: dict[str, list[dict]] | None = None` parameter to `build_generation_prompt()`.

In the slot rendering loop (where it currently prints feat options), add logic:
- If `ranked_feats` has an entry for this slot (`f"{level}_{slot_type}"`):
  - Print feats marked `show_description=True` with their description
  - Print remaining feat names in a compact list
- If no ranking: current behavior unchanged

Replace the current feat rendering block inside `build_generation_prompt` (the `for so in slots_by_level[level]:` loop body) with logic that checks for ranked feats:

```python
            if so.slot.slot_type == "skill":
                if not skill_feats_printed:
                    _append_grouped_skill_feats(parts, so)
                    skill_feats_printed = True
                else:
                    parts.append(f"  {slot_label} FEAT slot: pick from the skill feat list above (level {level} or lower)")
            elif ranked_feats and slot_key in ranked_feats:
                ranked = ranked_feats[slot_key]
                featured = [r for r in ranked if r.get("show_description")]
                rest = [r["name"] for r in ranked if not r.get("show_description")]
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options, top {len(featured)} recommended for this concept):")
                for r in featured:
                    line = f"    ★ {r['name']} (lvl {next((o.level for o in so.options if o.name == r['name']), '?')})"
                    if r.get("description"):
                        line += f" — {r['description']}"
                    parts.append(line)
                if rest:
                    parts.append(f"    Other options: {', '.join(rest)}")
            elif len(so.options) > 30:
                # existing behavior for large unranked lists
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options):")
                names = [opt.name for opt in so.options]
                parts.append(f"    {', '.join(names)}")
            else:
                # existing behavior for small unranked lists
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options):")
                for opt in so.options:
                    line = f"    - {opt.name} (lvl {opt.level})"
                    if opt.prerequisites:
                        line += f" [prereq: {opt.prerequisites}]"
                    if opt.rarity != "common":
                        line += f" [{opt.rarity}]"
                    parts.append(line)
```

Note: `slot_key = f"{level}_{so.slot.slot_type}"` needs to be computed before the if/elif chain.

- [ ] **Step 2: Verify the change doesn't break non-ranked prompts**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "
from orchestrator.prompt_builder import build_generation_prompt
from query.decomposer import get_build_options

opts = get_build_options('fighter', 5, 'human', [])
prompt = build_generation_prompt('melee fighter', opts)
print(f'Prompt length: {len(prompt)} chars')
print('Has feat options:', 'FEAT slot' in prompt)
"`

Expected: same prompt length as before, no breakage.

- [ ] **Step 3: Commit**

```bash
git add mcp-pf2e/orchestrator/prompt_builder.py
git commit -m "feat(prompt_builder): support ranked feat display with descriptions in generation prompt"
```

---

### Task 3: Wire ranking into pipeline

**Files:**
- Modify: `mcp-pf2e/orchestrator/pipeline.py`

Add `use_vector_ranking` parameter to `run_build()`. When enabled, initialize `PF2eDB`, call `rank_feats_for_concept()`, pass ranked feats to prompt builder. Handle VRAM: only unload mxbai for large (32B+) models.

- [ ] **Step 1: Add parameter and ranking step**

Add `use_vector_ranking: bool = False` to `run_build()` signature.

After the decomposer step and before prompt building, add:

```python
    # Step 2.5: Rank feats by concept relevance (optional, requires ChromaDB + mxbai)
    ranked_feats = None
    if use_vector_ranking:
        try:
            from server.db import PF2eDB
            from query.feat_ranker import rank_feats_for_concept

            if verbose:
                print(f"[pipeline] Ranking feats by concept relevance via ChromaDB...")
            t0_rank = time.time()
            db = PF2eDB()
            ranked_feats = rank_feats_for_concept(request, options, db)
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
        except Exception as exc:
            if verbose:
                print(f"[pipeline] WARNING: Vector ranking failed ({exc}), proceeding without ranking")
            ranked_feats = None
```

Update the prompt building call to pass ranked feats:

```python
    generation_prompt = build_generation_prompt(request, options, output_format, ranked_feats=ranked_feats)
```

- [ ] **Step 2: Update `build_generation_prompt` call**

The existing call is:
```python
    generation_prompt = build_generation_prompt(request, options, output_format)
```

Change to:
```python
    generation_prompt = build_generation_prompt(request, options, output_format, ranked_feats=ranked_feats)
```

- [ ] **Step 3: Verify**

Run: `cd /home/labrat/projects/path2charter/mcp-pf2e && python -c "from orchestrator.pipeline import run_build; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/orchestrator/pipeline.py
git commit -m "feat(pipeline): wire vector DB feat ranking into generation when use_vector_ranking=True"
```

---

### Task 4: Activate config flag and add benchmark configs

**Files:**
- Modify: `mcp-pf2e/benchmarks/runner.py`
- Modify: `mcp-pf2e/benchmarks/suite.json`

- [ ] **Step 1: Add `use_vector_ranking` to SUPPORTED_CONFIG_KEYS in runner.py**

```python
SUPPORTED_CONFIG_KEYS = {
    "id", "model", "judge_model", "schema_enforced", "temperature",
    "max_repairs", "use_vector_ranking", "notes",
}
```

- [ ] **Step 2: Pass `use_vector_ranking` to `run_build()` in `run_case()`**

Add to the `run_build()` call:
```python
        use_vector_ranking=config.get("use_vector_ranking", False),
```

- [ ] **Step 3: Add Mistral-Small with ranking config to suite.json**

Add a new run config for apples-to-apples comparison:

```json
    {
      "id": "mistral-with-ranking",
      "model": "ollama-mistral-small",
      "judge_model": "qwen3:32b",
      "schema_enforced": true,
      "temperature": 0.5,
      "max_repairs": 2,
      "use_vector_ranking": true,
      "notes": "Mistral-Small + vector DB feat ranking"
    }
```

- [ ] **Step 4: Commit**

```bash
git add mcp-pf2e/benchmarks/runner.py mcp-pf2e/benchmarks/suite.json
git commit -m "feat(benchmarks): activate use_vector_ranking flag, add mistral-with-ranking config"
```

---

### Task 5: Benchmark wizard-illusionist and exemplar-thrown

**Files:**
- No code changes. Benchmark run.

- [ ] **Step 1: Run the two failing cases with and without ranking**

```bash
cd /home/labrat/projects/path2charter/mcp-pf2e
python -m benchmarks.runner --configs mistral-small-schema-on mistral-with-ranking --cases wizard-illusionist exemplar-thrown
```

This runs 2 cases × 2 configs = 4 builds. Same model (Mistral-Small), same judge (Qwen3), only difference is `use_vector_ranking`.

- [ ] **Step 2: Compare results**

```bash
python -m benchmarks.report show <run_id>
python -m benchmarks.report compare <run_id>
```

Target: at least one of the two cases flips from INVALID to VALID with ranking enabled.

- [ ] **Step 3: If successful, run full suite with ranking**

```bash
python -m benchmarks.runner --configs mistral-with-ranking
```

---

## Future Phases (not implemented now)

### Phase 2: Skeleton-informing via cross-collection search
Before the skeleton pass, embed the concept and search across all collections (feats, class features, spells, equipment). Aggregate which class/ancestry appears most in top results. Feed this evidence into the skeleton prompt: "Semantic search found these Fighter feats and Champion features most relevant to 'thrown weapons + defense.'" The LLM makes a better-informed class choice.

### Phase 3: Prerequisite dependency chain analysis
Present feat choices as paths, not isolated picks:
```
Rebounding Toss (lvl 1) → Knockdown (lvl 4, needs Athletics) → Improved Knockdown (lvl 10)
```
This helps the model understand the cost of picking or skipping a feat. Without it, the model picks feats without understanding downstream consequences. Implementation: build a DAG from prerequisite data, find chains that include ranked feats, present them as ordered paths in the prompt.

---

## Self-Review

1. **Spec coverage:**
   - [x] Phase 1 only — feat ranking per slot
   - [x] Prerequisite chain members included in top-N
   - [x] Top 10 class, top 5 others
   - [x] VRAM: only unload mxbai for LARGE_MODELS
   - [x] Apples-to-apples benchmark: same model, with/without ranking
   - [x] `use_vector_ranking` config flag activated
   - [x] Phases 2 and 3 documented but not implemented

2. **Placeholder scan:** None found.

3. **Type consistency:**
   - `rank_feats_for_concept()` returns `dict[str, list[dict]]` — consumed by prompt_builder
   - `build_generation_prompt()` accepts `ranked_feats: dict[str, list[dict]] | None`
   - `run_build()` accepts `use_vector_ranking: bool`
   - Runner passes config flag through to `run_build()`
