# Scratchpad Experiment Plan

**Date:** 2026-04-24
**Goal:** Test whether visibility improvements in Pass 1 prompts reduce validation errors, and diagnose whether errors are visibility-level or state-tracking-level.

---

## Phase 0: Prompt Structure Refactor

Split user prompts into static prefix / dynamic suffix for KV cache reuse.

- [x] Keep system prompts as system role (unchanged)
- [x] Refactor `build_plan_prompt()`: static instructions + feat options first, dynamic concept/dedications/scratchpad at end
- [ ] Refactor `build_generation_prompt()`: same split (lower priority, Pass 2 has locked feats)
- [x] Verify no regression: variant (a) at n=15 serves as refactor check against historical baseline

## Phase 1: Implement Scratchpad Variants

### Variant (a) — Baseline
Current pipeline after Phase 0 refactor. No scratchpad.

### Variant (b) — Reminder Scratchpad
Appended at end of dynamic suffix in Pass 1:
```
=== BUILD STATE TRACKING ===
As you select feats, carefully track:
- Which feats you have already selected — NEVER pick the same feat twice
- Which skills your selected feats will require — you must ensure these are trainable
- Dedication rule: you need 2+ non-dedication archetype feats from a dedication before taking another Dedication feat
- Fill ALL feat slots — do not leave any empty
```

### Variant (c) — Cheap Annotated Candidates
Same scratchpad as (b), plus feat candidates annotated with prereq status against **starting state only** (class skills, base ability scores). No per-slot updating — that would be progressive generation.

Marks: `[ok]` prereqs met by starting state, `[!]` skill prereq NOT met, `[-]` ability score prereq (can't check without knowing boosts).

### Implementation
- [x] Extract feat option listing into shared `_build_feat_options_block()`
- [x] Add `_check_prereq_against_starting_state()` for variant (c) annotations
- [x] Add `scratchpad_mode` parameter to `build_plan_prompt()` ("none"/"reminder"/"annotated")
- [x] Wire `scratchpad_mode` through `pipeline.py` `run_build()`
- [ ] Compute starting skills from class data for annotation
- [x] Add suite.json configs for all 6 combos
- [ ] Add CLI flag for scratchpad mode

## Phase 2: Run Experiment

**Cases:**
- thaum-champion (n=15 per variant)
- dual-dedication (n=15 per variant)

**Models:**
- Mistral Small at t=0.55

**Total:** 1 model × 3 variants × (15 + 15) = **90 builds** (~1.5 hours)

## Results (run 2026-04-24_004)

### Validity Rates

| Variant | thaum-champion | dual-dedication | Overall |
|---------|---------------|-----------------|---------|
| none (baseline) | 80.0% (12/15) | 46.7% (7/15) | 63.3% |
| reminder | 93.3% (14/15) | 40.0% (6/15) | 66.7% |
| annotated | 93.3% (14/15) | 20.0% (3/15) | 56.7% |

### Error Category Breakdown

| Error Type | none | reminder | annotated |
|-----------|------|----------|-----------|
| dedication_rule | 7 | 8 | **16** |
| feat_prereq_chain | 2 | 5 | 3 |
| skill_prereq | 3 | 2 | 5 |
| duplicate | 0 | 0 | 2 |
| proficiency_level | 0 | 0 | 2 |

### Diagnosis

The aggregate null result hides a **strong case interaction**:

1. **thaum-champion** (local visibility problem): 80% → 93% with both scratchpad variants. Skill-prereq errors on simple feat chains are visibility-bound — showing prereq info inline fixes them.

2. **dual-dedication** (global coordination problem): 47% → 40% → **20%**. Dedication-ordering errors more than doubled with annotation (7 → 16). The extra per-feat information actively **destabilizes** the model's dedication reasoning, probably via attention displacement — per-slot detail crowds out whatever signal the model was using to track "am I allowed to take a second dedication here?"

**Two different failure modes require two different fixes:**
- Local visibility → progressive generation (per-slot candidate filtering with running state)
- Global coordination → deterministic locked slots (path-seeking architecture, not LLM reasoning)

### Diagnostic Matrix Outcome

Does not cleanly map to one row. Closest to a split:
- (b) helps on thaum-champion → **visibility is part of the bottleneck** for local decisions
- (c) hurts dual-dedication → **state-tracking failure** for global ordering, and more info makes it worse

**Implication:** Progressive generation alone would localize feat decisions (good) and pass running state (good for duplicates/skill prereqs), but would NOT solve dedication ordering. The model still can't reason about "have I taken 2+ Champion archetype feats?" even with more information. Only deterministic code handling dedication ordering fixes this — which is the locked-slot mechanism from path-seeking.

### Methodology Note

The experiment overturned the n=1 probe's aggregate "neither helps" conclusion. The case-interaction pattern (scratchpad helps one case, actively hurts another) was invisible at n=1. This is a concrete counter-example for future "can we skip confirmation?" decisions — 1.5 hours of GPU time bought a genuinely different architectural understanding.

## Architectural Recommendation

**Progressive generation for free slots + path-seeking with locked slots for goal-driven requirements.** The combined architecture is motivated by this experiment more strongly than progressive generation alone, because the dual-dedication regression demonstrates that better per-slot information doesn't fix global ordering constraints.
