# Implementation Plan: Progressive Generation (Agentic Loop)

**Date:** 2026-04-24
**Pattern:** ReAct-style agentic loop with deterministic state manager
**Scope:** This iteration — progressive generation + dedication locking
**Deferred:** Full path-seeking (goal extraction + backward dependency resolution) — next iteration, conditional on benchmark results

---

## Motivation

The scratchpad experiment (2026-04-24, 90 builds n=15) revealed two distinct failure modes:

1. **Local visibility** (skill prereqs on individual feat choices): fixable with inline information. thaum-champion 80% → 93%.
2. **Global coordination** (dedication ordering across the build): unfixable by giving the LLM more info — annotated scratchpad made it worse (47% → 20%, dedication errors doubled 7 → 16).

These require different fixes:
- Progressive generation solves local visibility by presenting one slot at a time with filtered candidates and running state.
- Deterministic dedication locking solves global coordination by removing dedication ordering from LLM reasoning entirely.

## Architectural Context

### What This Iteration Covers
- Per-slot progressive generation loop (forward execution) — slot types include class/ancestry/general/skill feats **and skill increases**
- Upfront deterministic ability score plan (one LLM priority call → immutable `AbilityPlan` with level-indexed scores)
- Upfront starting skill allocation (one LLM priority call, same call as ability priority)
- Candidate filtering using running state (duplicates, prereqs, ability score lookups, skill proficiency tracking)
- Deterministic dedication slot locking (narrow path-seeking for dedications only)

### What This Iteration Does NOT Cover (Deferred)
Full path-seeking has four phases:
1. **Goal selection** — LLM picks 2-4 target feats from candidate pool
2. **Backward dependency resolution** (deterministic) — code walks backward from goals to collect required feats, skills, ability scores
3. **Collision detection** (deterministic) — code checks joint feasibility of goals
4. **Forward execution** — LLM fills free slots level-by-level with locked slots pre-placed

This plan implements phase 4 with a thin version of phase 3 (dedications only). Phases 1 and 2 are deferred because:
- Progressive generation alone addresses three of four dominant error categories (skill prereqs 34%, duplicates 19%, missing slots 19%)
- Don't build two untested architectural layers simultaneously
- Path-seeking's marginal value can only be assessed after progressive gen is benchmarked
- If progressive takes hard-case validity to 85%+, full path-seeking may be unnecessary
- If goal-coherence failures appear in error analysis (locally legal feats that don't build toward anything), path-seeking becomes the clear next step

**The architectural north star remains:** progressive gen for free slots + path-seeking with locked slots for goal-driven requirements. This iteration stabilizes the foundation; the next adds the planning layer if needed.

---

## Design

### Pattern: ReAct-Style Agentic Loop

```
for each slot in build order:
    OBSERVE  → current CharacterState + filtered candidates for this slot
    REASON   → LLM picks one feat from narrowed candidates (scoped prompt)
    ACT      → deterministic state update (feat added, skills committed, archetype counts adjusted)
    VALIDATE → per-step validation against running state
```

The controller (Python code) holds authoritative state. The LLM is called with that state + a narrow, scoped decision prompt. A deterministic component updates state based on the LLM's output. This is the canonical agentic loop pattern — directly portable to any structured generation problem.

### Upfront Setup: AbilityPlan + Starting Skills

Before the progressive loop begins, one LLM call resolves the two thematic judgment calls that can't be mechanized:

1. **Ability priority order** — which abilities get the free boosts (e.g., "intimidating goblin champion" → Cha > Str > Con)
2. **Skill training priority** — which skills get the free training slots beyond class grants (e.g., Intimidation, Religion, Diplomacy)

One call, two questions, then fully deterministic from there.

```python
@dataclass
class AbilityPlan:
    """Computed once at setup. Immutable during generation."""
    scores_by_level: dict[int, dict[str, int]]
    # e.g., scores_by_level[1]  = {"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 8, "cha": 18}
    #       scores_by_level[5]  = {"str": 18, "dex": 14, "con": 14, "int": 10, "wis": 10, "cha": 19}
    #       scores_by_level[10] = {"str": 19, "dex": 16, "con": 16, "int": 12, "wis": 12, "cha": 20}
    priority_order: list[str]   # LLM-chosen, for reference
```

**Construction:** Read ancestry fixed boosts/flaws + background boosts + class key ability from static data. Apply fixed boosts to base 10. Distribute free boosts by LLM-provided priority order (highest-priority ability first, subject to per-event boost limit: each ability can receive at most one boost per boost event — L1 free boosts are one event, each level-up is one event; an ability *can* be boosted at every event, just not twice within the same event). Apply level-up boosts at 5/10/15/20 (same priority, +2 below 18, +1 at/above 18, 4 boosts per event each to a different ability). Store the full score block at each boost level. Interpolate between: scores don't change between boost levels, so `scores_by_level[3]` = `scores_by_level[1]`.

### State Manager

```python
@dataclass
class CharacterState:
    # Identity
    class_name: str
    ancestry_name: str
    character_level: int

    # Immutable plans (computed at setup)
    ability_plan: AbilityPlan               # level-indexed ability scores, lookup only
    
    # Feat tracking (mutated during loop)
    feats_chosen: list[ParsedFeatChoice]    # running list
    dedications_taken: list[str]            # dedication names in order
    archetype_feat_counts: dict[str, int]   # dedication_name → count of non-dedication archetype feats
    locked_slots: dict[str, str]            # "level_slottype" → feat name (pre-assigned by dedication planner)

    # Skill tracking (mutated during loop — skill increases are slot types)
    skills: dict[str, str]                  # skill → rank, updated as skill increase slots are filled
```

**Key simplification vs. prior plan version:** Ability scores are no longer tracked as mutable budgets during the loop. They're pre-computed and immutable — filter predicates do O(1) lookups (`ability_plan.scores_by_level[level][ability] >= required`), not reachability calculations. Skills are tracked incrementally because skill increases are slot types the loop fills — each skill increase slot commits a rank-up, updating `skills`.

### Candidate Filtering

Existing validator rules become pre-filters. For each slot, before calling the LLM:

1. **Remove duplicates** — feats already in `feats_chosen` (except repeatables)
2. **Remove unmet feat prereqs** — check feat-requires-feat against `feats_chosen`
3. **Enforce dedication ordering** — only allow a second dedication if `archetype_feat_counts[first_dedication] >= 2`
4. **Check ability score prereqs** — simple lookup: `ability_plan.scores_by_level[slot_level][ability] >= required`. No reachability math — the plan is already committed.
5. **Check skill prereqs** — verify `state.skills[skill] >= required_rank`. Skills are committed incrementally as skill increase slots are filled during the loop. For feats at levels before all skill increases have been assigned, use the current committed state — if a skill isn't trained yet, the feat is filtered out. This is correct because skill increases are earlier in level order (they're separate slot types the loop processes).
6. **Skip locked slots** — if this slot is pre-assigned by dedication planner, apply directly without LLM call

The key insight: this is the same logic as `check_archetype_rules()`, `check_prerequisites()`, `check_duplicate_feats()` in `validator/rules.py`, but expressed as predicates ("is this legal given current state?") rather than post-hoc error reports ("this was illegal").

**Why this is simpler than reachability tracking:** Ability scores are pre-committed (immutable plan, O(1) lookups). Skills are committed incrementally as the loop processes skill increase slots in level order. At any given feat slot, the filter checks against *actually committed* state, not projected budgets. The loop processes slots in level order, so skill increases at L3 are committed before class feats at L4 are filtered. No budget tracking, no overcommitment detection — the state is always authoritative.

**Slot ordering matters:** The progressive loop processes all slots at a given level before moving to the next level. Within a level, skill increase slots are processed first (if present), then feat slots. This ensures skill proficiencies are committed before feat prereqs are checked at that level.

### Dedication Locking (Narrow Path-Seeking)

Before the progressive loop, if dedications are requested:

1. For each requested dedication, look up the dedication feat and its level requirement
2. Assign the first dedication feat to the earliest eligible class feat slot
3. For dual+ dedications: assign 2 non-dedication archetype feats from the first dedication to the next available class feat slots, then assign the second dedication feat to the slot after those
4. If there aren't enough class feat slots between dedications to fit the 2 required archetype feats, the dedication schedule is infeasible at this level — report error before entering the loop
5. Mark all assigned slots as locked in `CharacterState.locked_slots`

**Edge case — tightly spaced dual dedications:** If the user requests two dedications and available class feat slots are e.g. L2, L4, L6, L8, the scheduler assigns: L2 = first dedication, L4 + L6 = archetype feats from first dedication, L8 = second dedication. This works. But if slots are L2, L4, L6 only (3 class feat slots total), dual dedication is infeasible — you need at minimum 4 class feat slots (ded1, arch, arch, ded2). The scheduler detects this and fails early rather than producing a broken build.

**Scope limit:** This iteration handles single dedications fully and dual dedications where the slot schedule is feasible. Triple+ dedications or builds where the required archetype feats have their own complex prereq chains are deferred to full path-seeking, which handles them naturally through backward dependency resolution.

This is deterministic — no LLM involvement. The dual-dedication case that regressed in the scratchpad experiment would have dedication ordering enforced by construction.

### Per-Slot Prompting

Each LLM call gets a narrow prompt:
- Current slot type and level
- Filtered candidate list (names + brief prereq notes)
- Running state summary (feats chosen so far, skills committed, theme reminder)
- The original build concept (for thematic coherence)
- For skill increase slots: list of skills eligible for increase, current ranks

This is much smaller than the current Pass 1 prompt (which presents all slots at once). Smaller prompt → less attention displacement → better per-slot decisions.

**Low priority:** Including ability scores at current level in the state summary as thematic context (e.g., "Your Str is 18 at this level" helps the LLM understand build identity). Try without first, add if theme scores drop.

---

## Implementation Steps

### Step 1: Upfront Setup — AbilityPlan, Starting Skills, Dedication Locking
**File:** `orchestrator/progressive.py` (new)

- [ ] Create `AbilityPlan` dataclass with `scores_by_level: dict[int, dict[str, int]]`
- [ ] Create `CharacterState` dataclass with all fields (identity, ability_plan, feats, skills, locked_slots)
- [ ] Add `static_reader` helpers:
  - `get_ancestry_boosts(ancestry_name) → (fixed_boosts, free_boost_count, flaws)` — parse ancestry JSON `system.boosts` / `system.flaws`
  - `get_background_boosts(background_name) → (fixed_options, free_boost_count)` — parse background JSON `system.boosts`
  - `get_class_key_ability(class_name) → list[str]` — parse class JSON `system.keyAbility.value`
  - `get_skill_increase_levels(class_name) → list[int]` — parse class JSON `system.skillIncreaseLevels`
- [ ] Implement upfront LLM priority call:
  - One call returning: ability priority order (list of 6 abilities) + skill training priorities (top N skills for free training slots)
  - Schema-constrained response for reliability
  - Takes: build concept, class, ancestry, available skills, number of free training slots
- [ ] Implement `compute_ability_plan(ancestry, background, class_key, priority, level) → AbilityPlan`
  - Base 10 for all abilities
  - Apply ancestry fixed boosts (+2 each) and flaws (-2 each)
  - Apply background boost (pick from fixed options based on priority) + free boost
  - Apply class key ability boost
  - Distribute 4 L1 free boosts by priority order (no double-boost per round)
  - Compute level-up boosts at 5/10/15/20 by priority order (+2 below 18, +1 at/above 18)
  - Store full score block at each boost level (1, 5, 10, 15, 20)
  - Validate: all scores even, none above level cap
- [ ] Implement `compute_starting_skills(class_name, background, int_score, skill_priority) → dict[str, str]`
  - Class fixed grants → trained
  - Background skill grants → trained
  - Int modifier free slots → fill from LLM skill priority list → trained
  - Result is initial `state.skills`
  - **Int-modifier dependency:** The number of free skill training slots depends on Int modifier, which depends on the AbilityPlan. Use the L1 Int score from the already-computed AbilityPlan (which is available because `compute_ability_plan` runs first). If the LLM's priority order places Int high enough to grant an extra skill slot, that's reflected automatically. The upfront LLM call should be told how many free skill slots to prioritize for (computed from fixed-boost Int as a lower bound), but the actual count may be higher after the plan is computed. The allocator handles whichever number is available.
- [ ] Implement `plan_dedication_slots(options, dedications, ability_plan) → locked_slots`
  - Verify dedication ability score prereqs against `ability_plan.scores_by_level` at the slot's level before locking
  - Same scheduling logic as before (earliest eligible class feat slots, 2 archetype feats before second dedication)
- [ ] Extract filter pipeline into `filter_candidates(state, slot, slot_options) → filtered`
  - Duplicate check
  - Feat prereq check (has required feats in `state.feats_chosen`)
  - Ability score check: `state.ability_plan.scores_by_level[slot.level][ability] >= required`
  - Skill check: `state.skills[skill] >= required_rank`
  - Dedication ordering check

### Step 2: Per-Slot Prompt Builder
**File:** `orchestrator/prompt_builder.py` (extend existing)

- [ ] Add `build_slot_prompt(request, slot, filtered_candidates, state_summary) → str`
  - Includes concept reminder, running state, candidate list, slot context
  - Much shorter than full plan prompt — one slot, not all slots
- [ ] Add `build_slot_schema(filtered_candidates) → dict`
  - Single enum-constrained field, not multi-level structure
- [ ] Add `build_state_summary(state) → str`
  - Human-readable summary of feats chosen, skills committed, dedications taken
  - This is what the LLM sees as "context" for each slot decision

### Step 3: Progressive Build Controller
**File:** `orchestrator/progressive.py`

- [ ] Implement `progressive_build(options, request, model, ...) → result`
  - Run upfront LLM priority call (ability + skill priorities)
  - Compute `AbilityPlan` and starting skills deterministically
  - Initialize `CharacterState` with ability plan, starting skills, and locked slots
  - Build unified slot list from `options.slot_options` + skill increase slots (from `get_skill_increase_levels`)
  - Sort all slots by level, with skill increases processed before feat slots at the same level
  - Apply locked slots (dedication assignments)
  - For each remaining slot in level order:
    1. **If skill increase slot:** filter to skills eligible for rank-up (trained→expert at L3+, expert→master at L7+, etc.), LLM picks one, update `state.skills`
    2. **If feat slot:** filter candidates against running state (feats, ability plan, skills), LLM picks one, update state
    3. If only 1 candidate remains, auto-assign without LLM call — log as `auto_assigned: true`
    4. Build narrow prompt + schema
    5. Call LLM (`_call_ollama` from pipeline.py)
    6. Validate choice against state
    7. Update state
    8. Log step trace (slot_type, candidates_offered, candidates_after_filter, choice, auto_assigned, locked, llm_time)
  - After all slots: assemble final build JSON (feats from loop, ability scores from plan, skills from state, equipment/notes from one lightweight LLM call)
  - Run full validator for final check
  - Return result in same format as `_run_planned_generation()` for benchmark compatibility
  - **Auto-assign tracking:** Count and report `slots_total`, `slots_locked`, `slots_auto_assigned`, `slots_llm_decided` as top-level metrics in the result. Analysis must distinguish "LLM made good choices on N slots" from "filter pruned everything so the LLM only had real agency on M < N slots." A high-validity result with 60% auto-assigned slots is filter aggressiveness, not LLM improvement.

### Step 4: Final Build Assembly
**File:** `orchestrator/progressive.py`

After all slots (feats + skill increases) are filled:

- [ ] Assemble final build JSON:
  - `ability_scores`: from `state.ability_plan.scores_by_level[character_level]` — already computed, just read
  - `skills`: from `state.skills` — committed incrementally during the loop
  - `levels`: from `state.feats_chosen` — committed during the loop
  - `equipment` + `notes`: one lightweight LLM call with the complete build as context (thematic, not structural)
- [ ] Run full validator as final check (should produce zero errors if filter predicates are correct)

**Design note:** No end-of-loop allocator needed. Ability scores are pre-committed (immutable plan from setup). Skills are committed incrementally as skill increase slots are processed during the loop. Everything structural is deterministic.

### LLM Call Pattern Inventory

Three distinct call types, each schema-constrained:

| Call | When | Schema | Temperature | Purpose |
|------|------|--------|-------------|---------|
| **Priority call** | Once, before loop | `{ability_priority: [str x6], skill_priority: [str x N]}` | 0.7 (creative) | Thematic judgment: which abilities/skills matter for this concept |
| **Slot call** | Per slot during loop | `{choice: enum[filtered_candidates]}` | 0.5 (structured) | Pick one feat or skill increase from filtered options |
| **Assembly call** | Once, after loop | `{equipment: [str], notes: str}` | 0.7 (creative) | Thematic flavor for equipment and build rationale |

All three use `_call_ollama` with `response_format: json_schema`. The assembly call is not an afterthought — it has its own schema and receives the complete build as context. Implementation should treat each as a first-class call pattern with its own prompt builder and schema constructor.

### Step 5: Pipeline Integration
**File:** `orchestrator/pipeline.py`

- [ ] Add import and call to `progressive_build()` as alternative to `_run_planned_generation()`
- [ ] Wire through existing config parameters (temperature, model, ollama_options, verbose)
- [ ] Add `generation_mode` parameter: "planned" (current) or "progressive" (new)
- [ ] Keep `_run_planned_generation()` intact for A/B comparison

### Step 6: Benchmark Integration
**File:** `benchmarks/suite.json` + `benchmarks/runner.py`

- [ ] Add `generation_mode` to suite config schema and runner passthrough
- [ ] Create benchmark configs:
  - `mistral-progressive` — Mistral Small with progressive generation
  - `phi4-progressive` — Phi-4 with progressive generation
  - Keep baseline configs for A/B comparison
- [ ] Extend results.jsonl schema to include per-step trace data (slots filled, candidates offered per step, auto-assigned count)

### Step 7: Per-Step Trace Logging

- [ ] Add trace data to each progressive build result:
  ```json
  {
    "trace": [
      {"slot": "class_1", "candidates_offered": 45, "candidates_after_filter": 38, "choice": "Power Attack", "auto_assigned": false, "llm_time": 2.1},
      {"slot": "class_2", "candidates_offered": 42, "candidates_after_filter": 12, "choice": "Champion Dedication", "auto_assigned": true, "locked": true, "llm_time": 0},
      ...
    ],
    "slot_stats": {
      "slots_total": 12,
      "slots_locked": 3,
      "slots_auto_assigned": 2,
      "slots_llm_decided": 7,
      "by_type": {
        "class_feat": {"total": 5, "locked": 3, "auto": 0, "llm": 2},
        "ancestry_feat": {"total": 2, "locked": 0, "auto": 0, "llm": 2},
        "general_feat": {"total": 1, "locked": 0, "auto": 0, "llm": 1},
        "skill_feat": {"total": 2, "locked": 0, "auto": 1, "llm": 1},
        "skill_increase": {"total": 2, "locked": 0, "auto": 1, "llm": 1}
      }
    }
  }
  ```
- [ ] Trace data stored in build JSON files under `builds/benchmark/`
- [ ] Include in results.jsonl as nested structure

---

## Measurement Milestone (Post-Implementation)

Implementation completes at Step 7. This section is a separate gated milestone — "build the thing" is distinct from "measure the thing." Do not call implementation done until this measurement pass is complete.

### Benchmark Run

- [ ] Run progressive configs on same cases as scratchpad experiment:
  - thaum-champion (n=15)
  - dual-dedication (n=15)
  - simple-fighter (n=5) — sanity check, not a gate. Controls for architecture regression on easy cases. If simple-fighter drops below 80% (baseline was ~80-100% across configs), the progressive architecture is hurting easy cases and something is wrong.
- [ ] Compare against baseline (mistral-sp-none from run 2026-04-24_004)

### Analysis Checklist

**"Did it work?" — effectiveness metrics:**
- [ ] Per-error-category deltas vs. baseline (primary metric)
- [ ] Trace analysis: where in the slot sequence do failures occur?
- [ ] Filter-vs-LLM attribution: report `slots_llm_decided / slots_total` ratio, **broken down by slot type** (class feat, ancestry feat, general feat, skill feat, skill increase). Filter aggressiveness on locked-slot-adjacent class feat picks (e.g., archetype feats after a dedication) is structurally different from filter aggressiveness on genuinely open general feat picks — aggregate ratio hides this.
- [ ] Theme/synergy regression check
- [ ] Thaum-champion diagnostic: regression below scratchpad 93%? If so, investigate information density hypothesis
- [ ] Simple-fighter sanity: no regression below 80%

**"Is it correct?" — mechanism verification:**
- [ ] Dedication-ordering errors: if > 0, treat as scheduler bug, not LLM failure
- [ ] Duplicate errors: if > 0, treat as filter bug, not LLM failure
- [ ] Ability score errors: if > 0 (odd scores, above max, key ability too low), treat as AbilityPlan computation bug
- [ ] Ability score prereq errors: should be zero — AbilityPlan lookup in filter predicates prevents these by construction
- [ ] Skill increase slot coverage: are all skill increases at L3/5/7/... being processed? Any skipped?

**"What's next?" — architectural decision:**
- [ ] Path-seeking decision: do remaining errors show goal-coherence failures?

---

## Success Criteria

**Primary:** Dual-dedication validity >= 70%. The scratchpad baseline was 47%; matching that is non-regression, not success. 70% demonstrates that dedication locking + progressive filtering actually work as hypothesized. If we hit 50-60%, that's informative (some improvement, more needed) but not success — the plan should be reassessed.

**Secondary:**
- Thaum-champion validity >= 93% (diagnostic, not just a floor — if this regresses below the scratchpad-annotated result, it signals that per-slot narrowing loses cross-slot interaction visibility. Progressive gen presents less context per call than the scratchpad's all-at-once view; the LLM's attention allocation is different in the two regimes. A regression here would be informative about information density vs. decision locality.)
- Dedication-ordering errors = 0. This is a **correctness test for the locking mechanism**, not a hoped-for outcome. If dedication-ordering errors appear, the dedication scheduler has a bug — investigate the scheduler, not the LLM.
- Duplicate errors = 0. Same: this is a **correctness test for the candidate filter**. If duplicates appear, the filter predicate has a bug. Investigate the filter.
- Skill-prereq errors reduced vs. baseline (skills committed incrementally as skill increase slots are filled during loop; feat prereqs checked against committed state)
- Ability score errors (odd, above max, key ability too low) = 0. **Correctness test for AbilityPlan computation.** These are currently LLM-generated; deterministic computation eliminates them by construction.
- No theme/synergy score regression > 0.5 points

**Filter-vs-LLM attribution:**
- Report `slots_llm_decided / slots_total` ratio alongside validity. If the LLM only had real agency on 40% of slots, a high validity rate is filter aggressiveness, not model improvement. Both are fine outcomes, but the interpretation is different and affects whether path-seeking is needed.

**Diagnostic (for path-seeking decision):**
- If remaining errors are "locally legal but globally incoherent" (feats that individually pass but don't build toward anything) → path-seeking needed
- If remaining errors are prereq chains the filter missed → improve filter predicates
- If validity > 85% on hard cases → path-seeking may be unnecessary, reassess

---

## What This Sets Up for Path-Seeking (Next Iteration)

If progressive generation benchmarks show goal-coherence failures, the next iteration adds:

1. **Goal extraction:** LLM picks 2-4 target feats from a curated candidate pool (high-level feats that define the build's identity)
2. **Backward dependency resolution:** Code walks backward from each goal through `prerequisite.py` to collect required feats, skills, ability scores
3. **Collision detection:** Code checks whether goals are jointly feasible (slot conflicts, ability score contradictions, skill budget overruns)
4. **Locked slot expansion:** Goals + dependencies get assigned to specific slots, expanding `CharacterState.locked_slots` beyond just dedications

The progressive loop from this iteration becomes phase 4 of the full path-seeking pipeline, unchanged. The state manager (with AbilityPlan + incremental skills), candidate filtering, per-slot prompting, and slot ordering all carry forward. This iteration's architecture is designed so path-seeking slots in on top without refactoring — the AbilityPlan is exactly what collision detection (phase 3) queries for ability score feasibility, and `state.skills` tracks the running skill state that prereq filtering needs.

### Post-Progressive Iteration Roadmap (Ordered by Dependency)

1. **Full path-seeking** — goal extraction + backward dependency resolution + collision detection (conditional on benchmark results, as above)
2. **Spell selection** — separate subsystem for casters; requires per-class spell list decomposition, slot/repertoire tracking
3. **Class-specific mechanics** — domains, schools, causes, etc. Per-class as needed
4. **Equipment optimization** — currently LLM-decided, low priority (no validation interaction)

---

## Non-Goals

- Framework adoption (LangGraph, LangChain) — pattern is portable without framework
- Constraint solver integration (MiniZinc) — interesting but a detour from current architecture
- Spell selection for casters — separate subsystem with its own complexity (repertoire vs. prepared, spell slots by level, etc.)
- Class-specific mechanics (Cleric domains, Wizard schools, Champion cause) — handle per-class as needed, not as blanket coverage
- Class-feature-granted skill bonuses — some classes get bonus skill trainings at specific levels beyond base cadence; handle as discovered
- Lore skills — specialized variants; defer to feat-level handling
- Free archetype variant rule — optional rule, deferred
- Equipment optimization — leave to LLM (genuinely creative, no validation interaction)
- New module structure — progressive.py lives in `orchestrator/`, not a new top-level directory

## Reference Reading

- ReAct paper (Yao et al. 2022, arXiv:2210.03629) — foundational pattern vocabulary
- Anthropic "Building effective agents" — production framing, thin loops over framework abstractions
- Project scratchpad experiment results (this repo, `docs/superpowers/plans/2026-04-24-scratchpad-experiment.md`) — the empirical motivation
