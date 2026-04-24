# Quality Fixes Plan — Build Completeness & Polish

**Date:** 2026-04-24
**Scope:** Four targeted fixes to improve build quality within the existing progressive architecture
**Estimated effort:** ~2 days total
**Prerequisite:** Progressive generation is working at 98.6% validity

---

## Context

Progressive generation produces valid, mechanically correct builds. The remaining quality gaps are:
- Equipment is hallucinated (every build)
- Skill feats default to "Additional Lore" when the LLM doesn't know what to pick (visible in 40%+ of builds)
- 44 archetypes with level-subdirectory structures silently return no feats
- Specific feat requests in concept text are honored ~50% of the time (no prereq chain → works; prereq chain → usually fails)

These are all fixable without architectural changes.

---

## Fix 1: Archetype Feat Reading Bug

**Effort:** 30 minutes | **Impact:** Unlocks 44 archetype dedications

**Problem:** `list_archetype_feats()` in `static_reader.py` uses `_list_feats_flat()`, which expects JSON files directly in the archetype directory. But 44 archetypes (including beastmaster, acrobat, alchemist, animist, archer, etc.) use `level-N/` subdirectories. These silently return empty feat lists, making dedication locking fail with "Dedication feat not found."

**Fix:** Change `list_archetype_feats()` to try level-subdirectory layout first, fall back to flat layout. Both patterns exist in the data (198 flat, 44 level-dir).

```python
def list_archetype_feats(archetype_name: str, max_level: int) -> list[FeatOption]:
    base_dir = _STATIC_ROOT / "feats" / "archetype" / _slugify(archetype_name)
    # Try level-subdirectory layout first (some archetypes use this)
    level_feats = _list_feats_from_level_dirs(base_dir, max_level)
    if level_feats:
        return level_feats
    # Fall back to flat layout
    return _list_feats_flat(base_dir, max_level)
```

**Verification:** `list_archetype_feats('beastmaster', 20)` returns 7+ feats instead of 0.

---

## Fix 2: Equipment from Data

**Effort:** Half day | **Impact:** Eliminates equipment hallucination in every build

**Problem:** The assembly LLM call generates freeform equipment strings. Results include D&D items ("Belt of Mighty Strength +4"), non-existent PF2e items ("Thaumaturge Spellbook"), and duplicates. Equipment is the most visible quality gap.

**Approach:** Replace freeform equipment generation with schema-constrained selection from the actual equipment database (5,622 items). The LLM picks from real items.

### Implementation

**Step 2a: Equipment data helpers** in `static_reader.py`
- [ ] `list_starting_equipment(max_level: int, types: list[str] | None) → list[dict]` — returns items filtered by level and type (weapon, armor, shield, equipment, kit)
- [ ] Filter to common rarity by default, level ≤ character level
- [ ] Return name + type + level + price for each item

**Step 2b: Budget tracking**
- [ ] Implement starting wealth table (PF2e CRB Table 10-10): L1=15gp through L20=89,000gp
- [ ] Track remaining budget as items are selected
- [ ] Pre-filter items by: level ≤ character level, price ≤ remaining budget, common rarity
- [ ] The LLM sees item prices in the candidate list so it can make budget-aware choices

**Step 2c: Equipment selection in progressive pipeline**
- [ ] Replace the freeform assembly call with structured equipment selection
- [ ] Category-by-category approach (similar to feat slots):
  1. Weapon(s): filtered by class proficiency, budget, level
  2. Armor: filtered by class proficiency, budget, level
  3. Shield (optional): filtered by budget, level
  4. Gear: remaining budget spent on adventuring gear, consumables, etc.
- [ ] Each category is a single LLM call with enum-constrained candidates showing name + price
- [ ] Running budget decremented after each category

**Step 2d: Fallback for large candidate lists**
- [ ] If filtered candidates exceed ~100 items, further narrow by: prioritize items at character level, then level-1, then level-2, etc.
- [ ] Equipment selection reuses the same `_call_ollama` + schema pattern as feat slot selection

**Verification:** Run 5 builds, check all equipment items exist in the database.

---

## Fix 3: Skill Feat Quality

**Effort:** 2-3 hours | **Impact:** Eliminates "Additional Lore" spam, improves thematic skill feat selection

**Problem:** The LLM picks "Additional Lore" repeatedly because it's always valid (repeatable, no prereqs) and the LLM defaults to it when nothing else seems relevant. In the L17 rapier fighter build, 7 of 8 skill feats were Additional Lore.

**Two-part fix:**

### 3a: Prereq lookahead in skill feat prompts
- [ ] Before each skill feat slot, check what feat prereqs appear at later levels in the same build
- [ ] Surface these as hints in the prompt: "Upcoming feats at later levels may require: expert in Intimidation, trained in Medicine"
- [ ] This gives the LLM a reason to pick skill feats that unlock future feats instead of defaulting to filler
- [ ] Implementation: scan remaining slot options for prereqs mentioning skills, extract unique skill requirements, add to `build_slot_prompt`

### 3b: Deprioritize filler feats after first pick
- [ ] After "Additional Lore" (or any repeatable feat) is taken once, move it to the end of the candidate list in subsequent slots
- [ ] The LLM still sees it as an option but it's no longer the easy first choice
- [ ] Implementation: in `filter_candidates`, sort results with already-taken repeatables last

**Verification:** Run the L17 rapier fighter build, count Additional Lore occurrences (target: ≤ 2).

---

## Fix 4: Named Feat Targeting

**Effort:** Half day | **Impact:** Builds match specific feat requests from concept text

**Problem:** When concept text says "Must have Two-Weapon Flurry" or "Must have Vicious Rend," the progressive loop picks feats slot-by-slot without awareness of these goals. Simple feats (no prereqs, available at current level) get picked ~50% of the time. Feats with prereq chains (Vicious Rend → Beastmaster Dedication → trained Nature) almost never get picked.

**Approach:** Extract named feats from concept text before the progressive loop starts. Verify they exist. Lock them into appropriate slots, same mechanism as dedication locking.

### Implementation

**Step 4a: Feat extraction from concept**
- [ ] Scan concept text against the feat index (5,975 feats) using sliding window of 1-5 words
- [ ] Match against lowercased feat names
- [ ] Filter out false positives: common words that happen to be feat names (e.g., "Fleet", "Shield Block" when not capitalized or not preceded by "must have" / "with" / "using")
- [ ] Heuristic: only extract feats that appear after signal phrases ("must have", "with the", "using", "feat", "has")

**Step 4b: Lock extracted feats into slots**
- [ ] For each extracted feat, find the earliest slot where it's a valid candidate (correct slot type, level requirement met)
- [ ] Check prereqs: if the feat requires other feats, extract those too (one level of backward resolution — not full path-seeking, just immediate prereqs)
- [ ] Lock into `state.locked_slots` before the progressive loop
- [ ] If a feat can't be placed (no valid slot, prereqs unresolvable), log a warning and continue without locking

**Step 4c: Prereq chain handling (lightweight)**
- [ ] For locked feats with feat prereqs (e.g., Vicious Rend requires Beastmaster Dedication): also lock the prereq into an earlier slot
- [ ] For locked feats with skill prereqs (e.g., Beastmaster Dedication requires trained Nature): add the skill to `skill_requirements` so `compute_starting_skills` includes it
- [ ] This is one level of backward resolution — not full path-seeking, but enough to handle most "must have X" requests
- [ ] Limit: chains deeper than 2 (feat requires feat requires feat) are not handled; those are path-seeking territory

**Verification:** Run the Vicious Rend gnome fighter build — should produce a build with Beastmaster Dedication + Vicious Rend.

---

## Ordering

1. **Fix 1** first (30 min) — unblocks Fix 4's ability to lock archetype feats
2. **Fix 3** second (2-3 hours) — improves every build's skill feat quality immediately
3. **Fix 4** third (half day) — requires Fix 1 for archetype prereq chains
4. **Fix 2** last (half day) — independent, most implementation work, can be done in parallel

Fixes 1-3 could ship in a single session. Fix 4 is a light session. Fix 2 is independent.

## What This Doesn't Address (Path-Seeking Territory)

- Goal feats with deep prereq chains (>2 levels)
- Multi-feat synergy optimization ("I want a grappling build" → code picks the whole grapple feat tree)
- Ability score optimization for specific feat prereqs discovered during planning
- Triple+ dedication scheduling

These remain deferred to the path-seeking iteration, which this work further motivates with concrete failing cases.
