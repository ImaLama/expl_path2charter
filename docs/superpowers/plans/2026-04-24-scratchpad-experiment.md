# Scratchpad Experiment Plan

**Date:** 2026-04-24
**Goal:** Test whether visibility improvements in Pass 1 prompts reduce validation errors, and diagnose whether errors are visibility-level or state-tracking-level.

---

## Phase 0: Prompt Structure Refactor

Split user prompts into static prefix / dynamic suffix for KV cache reuse.

- [x] Keep system prompts as system role (unchanged)
- [x] Refactor `build_plan_prompt()`: static instructions + feat options first, dynamic concept/dedications/scratchpad at end
- [ ] Refactor `build_generation_prompt()`: same split (lower priority, Pass 2 has locked feats)
- [ ] Verify no regression: variant (a) at n=15 serves as refactor check against historical baseline

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
- [ ] Wire `scratchpad_mode` through `pipeline.py` `run_build()`
- [ ] Compute starting skills from class data for annotation
- [ ] Add suite.json configs for all 6 combos
- [ ] Add CLI flag for scratchpad mode

## Phase 2: Run Experiment

**Cases:**
- thaum-champion (n=15 per variant)
- dual-dedication (n=15 per variant)
- simple-fighter (n=10 per variant — Format Tax control)

**Models:**
- Mistral Small at t=0.55 (optimal measured temp)
- Phi-4 at t=0.25 (optimal measured temp)

**Total:** 2 models x 3 variants x (15+15+10) = **240 builds** (~4 hours)

## Diagnostic Matrix

| Result | Diagnosis | Next Step |
|--------|-----------|-----------|
| (b) helps, (c) helps more | Visibility is bottleneck, adjacency amplifies | Progressive generation with per-slot filtering |
| (b) helps, (c) same as (b) | Reminder alone sufficient | Deploy scratchpad, defer progressive gen |
| (b) no help, (c) helps | Need decision-adjacent info, not just reminders | Progressive generation essential |
| Neither helps | State-tracking failure during autoregression | Decomposition (progressive gen) or grammar constraints |

## Predictions (falsifiable)

- Phi-4 gains more than Mistral overall (its errors map more directly to scratchpad fixes)
- Phi-4 on thaum-champion gains >15pp absolute (baseline 7%, need to reach ~25%+)
- Mistral's missing_prereq_feat errors persist (cheap-c can't fix dependency chains)
- If simple-fighter regresses >15pp for either variant, the scratchpad is hurting easy cases (Format Tax)

## Measurements

- Per-error-category deltas (primary metric, not just overall validity)
- Theme/synergy scores (watch for Format Tax)
- Paired comparison against baseline (same prompts) for higher power
- Report per-case, not just aggregated
