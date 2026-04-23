# Statistical Temperature Study

**Date:** 2026-04-23
**Prerequisite:** [Main Benchmark Report](benchmark-report-2026-04-23.md), [Temperature Sweep](benchmark-temperature-2026-04-23.md)
**Focus:** Statistically robust temperature comparison at n=15 per combination
**Wall time:** ~3.2 hours for 180 builds

---

## 1. Experiment Design

### Motivation

The earlier temperature sweep (run 005) tested 4 temperatures with n=2 per combination. At that sample size, a single lucky/unlucky build changes the validity rate by 50%. This study increases to n=15 per combination to produce statistically meaningful conclusions.

### Parameters

| Parameter | Value |
|-----------|-------|
| **Models** | Mistral Small 3.2 (24B), Phi-4 (14B) |
| **Temperatures** | 0.25, 0.40, 0.55 |
| **Cases** | thaum-champion (medium), dual-dedication (hard) |
| **Runs per combo** | 15 |
| **Total builds** | 2 x 3 x 2 x 15 = **180** |
| **Run ID** | 2026-04-23_006 |

### Why These Temperatures

- 0.25: Low end -- deterministic, follows highest-probability tokens
- 0.40: Slightly below our default 0.50 -- conservative exploration
- 0.55: Slightly above default -- moderate exploration

### Why These Cases

- **thaum-champion**: Medium difficulty, single dedication, tests basic constraint satisfaction
- **dual-dedication**: Hard, two dedications with ordering constraints, tests complex multi-step reasoning

Both cases were used in the earlier sweep, providing direct comparability.

---

## 2. Overall Results

| Config | Valid | Rate | 95% CI | Avg Time | Theme | Synergy | Overall |
|--------|-------|------|--------|----------|-------|---------|---------|
| **mistral-stat-t025** | **23/30** | **76.7%** | 59%-88% | 57s | 8.8 | 7.7 | **8.2** |
| **mistral-stat-t055** | **23/30** | **76.7%** | 59%-88% | 55s | 8.7 | 7.5 | **8.2** |
| mistral-stat-t040 | 19/30 | 63.3% | 46%-78% | 60s | 8.3 | 7.0 | 7.8 |
| phi4-stat-t025 | 12/30 | 40.0% | 25%-58% | 54s | 8.0 | 6.2 | 7.1 |
| phi4-stat-t040 | 10/30 | 33.3% | 19%-51% | 56s | 8.0 | 6.1 | 7.1 |
| phi4-stat-t055 | 8/30 | 26.7% | 14%-44% | 59s | 8.0 | 6.0 | 7.0 |

95% confidence intervals use the Wilson score method for binomial proportions.

### Key Observations

**Mistral:** t=0.25 and t=0.55 are statistically indistinguishable (both 76.7%, CI 59-88%). t=0.40 is lower (63.3%, CI 46-78%) but the confidence intervals overlap with both -- we cannot conclude t=0.40 is truly worse. At n=15 per case, the honest conclusion is: **temperature between 0.25 and 0.55 does not meaningfully affect Mistral's validity rate.**

**Phi-4:** Shows a downward trend (40% → 33% → 27%) as temperature increases from 0.25 to 0.55. This is the **opposite** of what the earlier n=2 sweep suggested (which showed phi4 crashing at 0.25). At n=15, phi4 does best at the lowest temperature. However, all three CIs overlap substantially, so the trend is suggestive but not conclusive.

---

## 3. Per-Case Breakdown

This is where the real story is. The two cases behave completely differently.

### thaum-champion (Medium)

| Config | Valid | Rate | 95% CI | Theme | Synergy | Overall |
|--------|-------|------|--------|-------|---------|---------|
| **mistral-stat-t025** | **15/15** | **100%** | 80%-100% | 8.5 | 7.7 | 8.2 |
| mistral-stat-t040 | 13/15 | 86.7% | 62%-96% | 8.4 | 7.3 | 8.0 |
| mistral-stat-t055 | 13/15 | 86.7% | 62%-96% | 8.5 | 7.5 | 8.0 |
| phi4-stat-t055 | 3/15 | 20.0% | 7%-45% | 7.5 | 5.3 | 6.4 |
| phi4-stat-t025 | 1/15 | 6.7% | 1%-30% | 7.3 | 4.8 | 6.1 |
| phi4-stat-t040 | 1/15 | 6.7% | 1%-30% | 7.4 | 5.0 | 6.2 |

**Mistral dominates thaum-champion.** 100% at t=0.25 (15/15), 87% at higher temps. This is a solved case for Mistral.

**Phi-4 almost completely fails** (1-3/15 across all temps). The single-dedication thaum-champion case is harder for Phi-4 than dual-dedication -- counterintuitive until you look at the error categories (see section 4).

### dual-dedication (Hard)

| Config | Valid | Rate | 95% CI | Theme | Synergy | Overall |
|--------|-------|------|--------|-------|---------|---------|
| **phi4-stat-t025** | **11/15** | **73.3%** | 48%-89% | 8.7 | 7.6 | 8.2 |
| mistral-stat-t055 | 10/15 | 66.7% | 42%-85% | 8.9 | 7.5 | 8.3 |
| phi4-stat-t040 | 9/15 | 60.0% | 36%-80% | 8.7 | 7.2 | 7.9 |
| mistral-stat-t025 | 8/15 | 53.3% | 30%-75% | 9.1 | 7.6 | 8.2 |
| mistral-stat-t040 | 6/15 | 40.0% | 20%-64% | 8.3 | 6.7 | 7.5 |
| phi4-stat-t055 | 5/15 | 33.3% | 15%-58% | 8.5 | 6.7 | 7.6 |

**Phi-4 at t=0.25 leads** on dual-dedication (73.3%). Mistral at t=0.55 is close (66.7%). CIs overlap, but the pattern is clear: phi4 excels at the case where Mistral struggles, and vice versa.

### The Case-Model Interaction

| | thaum-champion | dual-dedication |
|--|---------------|----------------|
| **Mistral best** | **100%** (t025) | 66.7% (t055) |
| **Phi-4 best** | 20% (t055) | **73.3%** (t025) |

The models have **complementary strengths**. Mistral excels at the single-dedication medium case. Phi-4 excels at the dual-dedication hard case. This is not a temperature finding -- it's a model-architecture finding that only emerged because n=15 per case gave enough resolution.

---

## 4. Error Category Analysis

The error profiles explain the per-case pattern.

### Mistral Errors

| Config | Invalid | Total Errors | Dominant Categories |
|--------|---------|-------------|-------------------|
| mistral-stat-t025 | 7 | 9 | missing_prereq_feat=5, dedication_order=2, duplicate=2 |
| mistral-stat-t040 | 11 | 13 | missing_prereq_feat=11, skill_prereq=2 |
| mistral-stat-t055 | 7 | 9 | missing_prereq_feat=4, dedication_order=4, skill_prereq=1 |

Mistral's dominant error is **missing_prereq_feat** (feats requiring other feats that weren't taken). This is a dependency-chain error -- the model picks Feat B without first taking Feat A. Temperature doesn't change the error profile meaningfully.

**Notably absent:** skill_prereq is barely present (0-2 per config). However, this is likely a **case-selection artifact** rather than Mistral having solved the skill prerequisite problem. The main benchmark showed skill_prereq at 34.1% of errors across 10 cases; the near-zero rate here reflects that thaum-champion and dual-dedication happen not to stress skill prerequisites heavily. Do not generalize "Mistral solved skill prereqs" beyond these two cases.

### Phi-4 Errors

| Config | Invalid | Total Errors | Dominant Categories |
|--------|---------|-------------|-------------------|
| phi4-stat-t025 | 18 | 29 | dedication_order=16, skill_prereq=9, missing_prereq_feat=3 |
| phi4-stat-t040 | 20 | 40 | dedication_order=15, skill_prereq=11, missing_prereq_feat=6 |
| phi4-stat-t055 | 22 | 40 | dedication_order=17, skill_prereq=9, missing_prereq_feat=9 |

Phi-4's dominant error is **dedication_order** (15-17 per config) -- taking a second dedication before having 2+ archetype feats from the first. This is a structural ordering constraint that 14B models consistently fail to reason about.

**Why Phi-4 fails thaum-champion:** thaum-champion has one dedication (Champion), and Phi-4's errors are dominated by skill_prereq on the Thaumaturge class feats. The model doesn't assign the right skill training for the feats it picks.

**Why Phi-4 succeeds at dual-dedication:** dual-dedication has an explicit dedication requirement in the prompt, and the goblin thaumaturge chassis has fewer skill-intensive feats. Phi-4 can mechanically follow "take Champion Dedication, then Medic Dedication" without needing to reason about prerequisites.

---

## 5. Comparison to Earlier Sweep (n=2)

The earlier sweep (run 005, n=2 per combo) produced several conclusions that n=15 overturns.

| Finding | Sweep (n=2) | Statistical (n=15) | Verdict |
|---------|-------------|-------------------|---------|
| "Phi-4 crashes at t=0.25" | 0/2 (0%) | 12/30 (40%) | **Wrong.** Small-sample noise. |
| "Mistral t=0.25 is best" | 2/2 (100%) | 23/30 (77%) | **Directionally right**, but overstated. |
| "Mistral U-shape (t025=t055 > t040)" | Yes | Yes (77% = 77% > 63%) | **Pattern holds** but may be noise (CIs overlap). |
| "Phi-4 t040-t060 plateau at 50%" | 0-1/2 | 33-40% | **Wrong.** Phi-4 trends downward, not plateau. |
| "Temperature barely matters for Mistral" | Unclear at n=2 | Confirmed: 63-77% range | **Confirmed.** |

### Confidence Interval Comparison

The sweep's n=2 produced useless CIs (e.g., 0/2 = CI [0%-66%], 2/2 = CI [34%-100%]). At n=15, CIs narrow to ~30-point ranges -- still wide but directionally useful.

| Config | Sweep CI | Statistical CI | Improvement |
|--------|----------|---------------|-------------|
| mistral-t025 | 34%-100% | 59%-88% | 37pp narrower |
| phi4-t025 | 0%-66% | 25%-58% | 33pp narrower |

n=30 per combo (the combined 2-case total) was the minimum viable sample size for this measurement. n=15 per case provides directional guidance but not conclusive statistical differentiation between nearby temperature points.

---

## 6. Quality Scores

### All Builds (Valid + Invalid)

Temperature has minimal impact on scores for either model. All Mistral configs score 7.8-8.2; all Phi-4 configs score 7.0-7.1. The variance is in validity, not quality.

### Valid-Only Builds

| Config | N Valid | Theme | Synergy | Overall |
|--------|--------|-------|---------|---------|
| mistral-stat-t025 | 23 | 8.8 | 8.0 | **8.5** |
| mistral-stat-t055 | 23 | 8.7 | 7.9 | **8.5** |
| mistral-stat-t040 | 19 | 8.2 | 7.2 | 7.9 |
| phi4-stat-t025 | 12 | 8.9 | 7.9 | 8.4 |
| phi4-stat-t040 | 10 | 8.9 | 7.9 | 8.4 |
| phi4-stat-t055 | 8 | 8.6 | 7.6 | 8.1 |

When builds are valid, both models produce comparable quality (8.1-8.5 overall). The gap is in how often they produce valid builds, not in the quality of those builds.

**Mistral t=0.40 dip:** Valid-only score is noticeably lower (7.9) than t=0.25/t=0.55 (8.5). This tracks with the validity dip -- t=0.40 produces both fewer valid builds *and* lower-quality valid builds for Mistral. Two metrics moving together in the same direction is less likely to be pure noise than either alone. Not conclusive at this sample size (CIs still overlap), but if a larger study is ever run, t=0.40 is the interesting point to characterize -- the endpoints appear stable while the midpoint may represent a genuine local minimum.

---

## 7. Conclusions

### Temperature Sensitivity

1. **Mistral is temperature-resilient.** Validity ranges from 63-77% across 0.25-0.55, with overlapping confidence intervals. No temperature in this range is conclusively better or worse. The apparent dip at t=0.40 may be real but cannot be confirmed at this sample size.

2. **Phi-4 trends toward lower temperature being better** (40% → 33% → 27%), overturning the earlier sweep's finding. The trend is suggestive but CIs overlap. The earlier "phi4 crashes at t=0.25" conclusion was definitively wrong -- an artifact of n=2.

3. **Temperature is not the lever.** The maximum spread across all temperature points for either model (~14pp for Mistral, ~13pp for Phi-4) is smaller than the model-to-model gap (~40pp on thaum-champion) and the case-to-case gap (~70pp for Phi-4 between cases). Architecture and model choice dominate temperature choice.

### The Real Finding: Case-Model Interaction

The most important result is not about temperature -- it's that **different models excel at different case types**, and this effect is much larger than any temperature effect:

- **Mistral** is strong on single-dedication medium-complexity builds (87-100% on thaum-champion)
- **Phi-4** is surprisingly strong on explicit dual-dedication builds (60-73% on dual-dedication)
- Neither model's weakness is addressable by temperature tuning

### Error Profiles Are Model-Specific, Not Temperature-Specific

- **Mistral's bottleneck:** missing_prereq_feat (feat dependency chains)
- **Phi-4's bottleneck:** dedication_order + skill_prereq (structural constraints + visibility)

These error profiles are stable across temperatures, confirming that the errors are architectural (pipeline visibility and constraint enforcement) rather than sampling-related. Each model's dominant error maps to a specific architectural remedy:

- **Mistral's missing_prereq_feat** → path-seeking's dependency resolver (walk backward from target feats, lock prerequisites into earlier slots)
- **Phi-4's dedication_order** → locked slots with dedication ordering in the filter predicate (structurally impossible to take a 2nd dedication too early)
- **Phi-4's skill_prereq** → annotated candidate lists or progressive generation with per-slot skill-state visibility

### What n=15 Taught That n=2 Couldn't

1. Small-sample conclusions about temperature can be **directionally wrong**, not just noisy
2. Per-case validity at n=15 reveals model-case interactions invisible at n=2-3
3. Error category breakdowns only become meaningful at n=15+ (enough invalid builds to see patterns)
4. The confidence intervals at n=15 are still too wide to distinguish nearby temperatures (63% vs 77% has overlapping CIs) -- temperature optimization requires n=50+ per combo to be conclusive

### Practical Recommendations

- **Default temperature: 0.50** (current default is fine; no temperature in 0.25-0.55 is conclusively better)
- **Focus on pipeline architecture**, not temperature tuning -- the error categories are structural
- **Per-case benchmarking at n=15+ is the minimum** for drawing model-selection conclusions
- **Note on statistical power for next experiments:** paired comparisons (same prompts, intervention vs baseline) have substantially more power than independent binomial comparison. For the scratchpad experiment, n=15 paired is roughly equivalent to n=30-40 unpaired. Design accordingly -- don't over-spec sample sizes

---

## Appendix

- Run ID: `2026-04-23_006`
- Results: `mcp-pf2e/benchmarks/results.jsonl`
- Suite configs: `mcp-pf2e/benchmarks/suite.json` (configs `*-stat-t*`)
- Total builds: 180
- Total wall time: ~3.2 hours
- Confidence intervals: Wilson score method, z=1.96 (95%)
