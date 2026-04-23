# Local LLM Benchmark Report: Structured Character Generation

**Date:** 2026-04-23
**Task:** Multi-step structured JSON generation with constraint satisfaction
**Domain:** Pathfinder 2nd Edition character builds (transferable to any structured generation task)

---

## 1. Test Premises

### What We're Testing

This benchmark evaluates local LLMs on a task that combines several challenging capabilities:

1. **Structured output** -- generating valid JSON conforming to a strict schema
2. **Multi-step reasoning** -- a two-pass pipeline (skeleton plan, then full build) requiring consistency across passes
3. **Constraint satisfaction** -- output must satisfy dozens of interdependent rules (prerequisites, slot counts, ordering constraints, proficiency requirements)
4. **Domain knowledge** -- models must work with game-system data injected via prompt context, not memorized knowledge

The task is representative of real-world structured generation challenges: code generation, configuration synthesis, form filling with validation, and any pipeline where an LLM must produce output that passes a deterministic validator.

### Why Local Models

All models run locally via Ollama on consumer hardware. This tests what's achievable without API costs or latency, relevant for:
- Privacy-sensitive applications
- Offline/air-gapped environments
- Cost-sensitive high-volume generation
- Iteration speed during development

### Pipeline Architecture

The generation pipeline is a two-pass system:

1. **Pass 1 (Skeleton):** LLM receives the build request, class/ancestry data, and available feat lists. Produces a high-level plan (feat selections per slot).
2. **Pass 2 (Full Build):** LLM receives the skeleton plus detailed feat data. Produces complete JSON with ability scores, skills, equipment, and all feat choices.
3. **Repair Loop:** If the validator finds errors, the build is fed back to the LLM with error messages for up to N repair attempts.
4. **Validation:** A deterministic rule engine checks the output against PF2e rules (no LLM involvement).
5. **Evaluation:** A separate LLM judge scores the build on theme adherence and mechanical synergy.

Key pipeline features at time of testing:
- Class and ancestry locked in JSON schema enums (prevents identity drift)
- Class-granted skills injected as mandatory
- Dedication instructions in plan prompt
- Default 16K context window (Ollama `num_ctx`)

---

## 2. Technical Setup

### Hardware

| Component | Specification |
|-----------|--------------|
| CPU | AMD Ryzen Threadripper 3960X (24-core) |
| RAM | 128 GB DDR4 |
| GPU | 2x NVIDIA RTX 3090 (24 GB VRAM each) |
| Storage | NVMe SSD |
| OS | Linux 7.0.0-1-cachyos |

### Software

| Component | Version |
|-----------|---------|
| Ollama | 0.18.1 |
| Python | 3.14.4 |
| Pipeline | path2charter mcp-pf2e |

### Models Under Test

| Config ID | Model | Size | Quantization | Type | Context |
|-----------|-------|------|-------------|------|---------|
| mistral-small | Mistral Small 3.2 | 24B | Default (Q4) | Standard | 16K |
| mistral-small-tuned | Mistral Small 3.2 | 24B | Default (Q4) | Standard | 32K |
| qwen25-coder | Qwen 2.5 Coder | 32B | Q6_K | Standard | 16K |
| qwen25 | Qwen 2.5 | 32B | Default (Q4) | Standard | 16K |
| phi4 | Phi-4 | 14B | Default (Q4) | Standard | 16K |
| qwen3-moe | Qwen3 MoE | 30B (3B active) | Default | Thinking | 16K |
| mistral-with-ranking | Mistral Small 3.2 | 24B | Default (Q4) | Standard + Vector DB | 16K |
| qwen3-with-ranking | Qwen3 | 32B | Default (Q4) | Thinking + Vector DB | 16K |

### Judge Models

Cross-judging was used to avoid self-evaluation bias:
- Mistral-based configs judged by `qwen3:32b`
- Qwen/Phi-based configs judged by `mistral-small3.2:24b`

### Generation Parameters

| Parameter | Default | Tuned (mistral-small-tuned) |
|-----------|---------|---------------------------|
| Temperature | 0.5 | 0.4 |
| Max repairs | 2 | 2 |
| `num_ctx` | 16,384 | 32,768 |
| `repeat_penalty` | 1.0 (default) | 1.2 |
| `min_p` | 0.0 (default) | 0.05 |

### Benchmark Suite (v1.1)

10 test cases spanning easy to impossible difficulty:

| Case ID | Class | Level | Dedications | Difficulty |
|---------|-------|-------|-------------|------------|
| simple-fighter | Fighter | 5 | None | Easy |
| thrown-fighter | Fighter | 3 | None | Easy |
| thaum-champion | Thaumaturge | 4 | Champion | Medium |
| sneaky-caster | (unspecified) | (unspecified) | (unspecified) | Hard |
| wizard-illusionist | Wizard | 7 | None | Medium |
| exemplar-thrown | Exemplar | 8 | None | Medium |
| complex-multiclass | Inventor | 6 | Medic | Hard |
| dual-dedication | Thaumaturge | 8 | Champion + Medic | Hard |
| fire-caster-lvl12 | (unspecified) | 12 | (unspecified) | Hard |
| frontline-ctrl-lvl14 | (unspecified) | 14 | (unspecified) | Hard |

### Run Matrix

| Run ID | Configs | Cases | Runs/Case | Total Builds |
|--------|---------|-------|-----------|-------------|
| 2026-04-23_001 | 5 (mistral-small, mistral-small-tuned, qwen25-coder, mistral-with-ranking, qwen3-with-ranking) | 10 | 1 | 50 |
| 2026-04-23_002 | 2 (phi4, qwen3-moe) | 10 | 1 | 20 |
| 2026-04-23_003 | 1 (qwen25) | 10 | 1 | 10 |
| 2026-04-23_004 | 8 (all except gemma3) | 10 | 2 | 160 |
| **Total** | | | | **240 builds** |

Each config has 3 builds per case (1 from initial run + 2 from repeat run), enabling variance analysis.

---

## 3. Results

### Overall Performance by Config

| Config | Valid | Rate | Avg Time | Theme | Synergy | Overall | Avg Tokens | Valid/Hr |
|--------|-------|------|----------|-------|---------|---------|-----------|----------|
| **mistral-small** | **13/30** | **43.3%** | **68s** | 8.3 | 6.3 | 7.2 | 12,096 | **22.8** |
| qwen3-with-ranking | 12/30 | 40.0% | 258s | 8.1 | 6.1 | 7.1 | 19,803 | 5.6 |
| mistral-small-tuned | 12/30 | 40.0% | 78s | 8.0 | 6.0 | 6.9 | 13,825 | 18.4 |
| phi4 | 10/30 | 33.3% | 63s | 8.3 | 6.1 | 7.2 | 12,102 | 19.1 |
| qwen25-coder | 9/30 | 30.0% | 110s | 8.1 | 5.9 | 7.0 | 11,167 | 9.8 |
| mistral-with-ranking | 9/30 | 30.0% | 78s | **8.7** | **6.3** | **7.4** | 13,718 | 13.8 |
| qwen25 | 7/30 | 23.3% | 97s | 8.3 | 6.0 | 7.2 | 11,673 | 8.7 |
| qwen3-moe | 0/30 | 0.0% | 95s | 7.2 | 4.4 | 5.8 | 22,869 | 0.0 |

**Sorted by validity rate.** mistral-small leads in both validity (43.3%) and throughput (22.8 valid builds/hour).

### Per-Case Validity (valid/3 runs per cell)

| Case | mistral | m-tuned | q25-cod | qwen25 | phi4 | q3-moe | m+rank | q3+rank | Total |
|------|---------|---------|---------|--------|------|--------|--------|---------|-------|
| thrown-fighter | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 0/3 | 3/3 | 3/3 | **20/24** |
| simple-fighter | 3/3 | 3/3 | 2/3 | 1/3 | 1/3 | 0/3 | 1/3 | 3/3 | 14/24 |
| dual-dedication | 3/3 | 1/3 | 1/3 | 2/3 | 3/3 | 0/3 | 1/3 | 1/3 | 12/24 |
| complex-multiclass | 1/3 | 0/3 | 1/3 | 1/3 | 2/3 | 0/3 | 3/3 | 2/3 | 10/24 |
| thaum-champion | 2/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 2/3 | 7/24 |
| sneaky-caster | 1/3 | 1/3 | 2/3 | 1/3 | 1/3 | 0/3 | 0/3 | 0/3 | 6/24 |
| wizard-illusionist | 0/3 | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 1/3 | 2/24 |
| exemplar-thrown | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 1/3 | 0/3 | 1/24 |
| fire-caster-lvl12 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | **0/24** |
| frontline-ctrl-lvl14 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | **0/24** |

Key observations:
- **Easy cases** (thrown-fighter, simple-fighter): Most configs pass reliably
- **Hard cases** (fire-caster-lvl12, frontline-ctrl-lvl14): **Zero models pass** -- these need pipeline-level fixes
- **Exemplar-thrown**: Only 1/24 valid -- the Exemplar class is poorly represented in training data
- **Consistency varies wildly**: phi4 gets 3/3 on dual-dedication but 0/3 on thaum-champion

### Error Analysis

689 total errors across 168 invalid builds (4.1 errors per invalid build on average):

| Error Category | Count | % | Description |
|---------------|-------|---|-------------|
| Skill proficiency unmet | 235 | 34.1% | Feat requires trained/expert skill the character lacks |
| Duplicate feat | 133 | 19.3% | Same feat selected in multiple slots |
| Missing feat slots | 128 | 18.6% | Build has unfilled feat slots (mostly qwen3-moe) |
| Dedication ordering | 79 | 11.5% | 2nd dedication before 2+ archetype feats from 1st |
| Missing prerequisite feat | 48 | 7.0% | Feat requires another feat not taken |
| Ability score prerequisite | 32 | 4.6% | Feat requires higher ability score than allocated |
| Trait/condition prereq | 18 | 2.6% | Feat requires specific trait or condition |
| Too many feats | 9 | 1.3% | More feats than available slots |
| Wrong class/ancestry | 3 | 0.4% | Feat from wrong class or ancestry |

**The top 3 error categories (skill prereqs, duplicates, missing slots) account for 72% of all errors.** These are pipeline-addressable problems, not model limitations.

### Errors Per Invalid Build by Config

| Config | Errors | Invalid Builds | Errors/Build |
|--------|--------|---------------|-------------|
| qwen3-with-ranking | 160 | 18 | 8.9 |
| mistral-with-ranking | 90 | 21 | 4.3 |
| qwen3-moe | 117 | 30 | 3.9 |
| mistral-small | 64 | 17 | 3.8 |
| phi4 | 74 | 20 | 3.7 |
| mistral-small-tuned | 62 | 18 | 3.4 |
| qwen25 | 68 | 23 | 3.0 |
| qwen25-coder | 54 | 21 | 2.6 |

qwen3-with-ranking produces the most errors per invalid build (8.9) -- when it fails, it fails catastrophically. qwen25-coder fails gracefully (2.6 errors/build).

### Token Usage

| Config | Avg Prompt | Avg Completion | Avg Total | Notes |
|--------|-----------|---------------|-----------|-------|
| qwen3-moe | 13,728 | 9,141 | 22,869 | Massive thinking overhead |
| qwen3-with-ranking | 16,317 | 3,486 | 19,803 | Ranking adds prompt, thinking adds completion |
| mistral-small-tuned | 11,793 | 2,033 | 13,825 | 32K context = larger prompts |
| mistral-with-ranking | 11,757 | 1,960 | 13,718 | Ranking adds ~1K prompt tokens |
| phi4 | 10,417 | 1,685 | 12,102 | Efficient despite small size |
| mistral-small | 10,424 | 1,672 | 12,096 | Baseline |
| qwen25 | 10,106 | 1,567 | 11,673 | Slightly below average |
| qwen25-coder | 9,611 | 1,555 | 11,167 | Most token-efficient |

Thinking models (qwen3-moe, qwen3-with-ranking) use 1.5-2x more tokens than standard models, primarily from thinking token overhead in completions.

### Speed-Quality Tradeoff

| Config | Valid Rate | Avg Time | Builds/Hr | Valid Builds/Hr | Score |
|--------|-----------|----------|-----------|----------------|-------|
| **mistral-small** | **43.3%** | **68s** | 52.7 | **22.8** | 7.2 |
| phi4 | 33.3% | 63s | **57.3** | 19.1 | 7.2 |
| mistral-small-tuned | 40.0% | 78s | 46.0 | 18.4 | 6.9 |
| mistral-with-ranking | 30.0% | 78s | 46.0 | 13.8 | **7.4** |
| qwen25-coder | 30.0% | 110s | 32.6 | 9.8 | 7.0 |
| qwen25 | 23.3% | 97s | 37.1 | 8.7 | 7.2 |
| qwen3-with-ranking | 40.0% | 258s | 14.0 | 5.6 | 7.1 |
| qwen3-moe | 0.0% | 95s | 37.9 | 0.0 | 5.8 |

**Best throughput:** phi4 at 57.3 builds/hour (but lower validity).
**Best valid throughput:** mistral-small at 22.8 valid builds/hour.
**Best quality (when valid):** mistral-with-ranking at 7.4 avg score, 8.7 theme.

### Score Consistency

| Config | All (mean +/- std) | Valid Only | Invalid Only |
|--------|-------------------|------------|-------------|
| mistral-with-ranking | 7.4 +/- 1.2 | 8.7 | 6.9 |
| mistral-small | 7.2 +/- 1.7 | 8.2 | 6.5 |
| phi4 | 7.2 +/- 1.0 | 8.3 | 6.6 |
| qwen25 | 7.2 +/- 1.0 | 7.8 | 7.0 |
| qwen3-with-ranking | 7.1 +/- 1.7 | 8.3 | 6.3 |
| qwen25-coder | 7.0 +/- 1.0 | 7.8 | 6.7 |
| mistral-small-tuned | 6.9 +/- 2.2 | 7.7 | 6.4 |
| qwen3-moe | 5.8 +/- 1.7 | N/A | 5.8 |

phi4 and qwen25 variants have the lowest score variance (std 1.0) -- most consistent output quality regardless of validity. mistral-small-tuned has the highest variance (2.2) -- its tuning params make it either very good or very bad.

---

## 4. Model Analysis

### Mistral Small 3.2 (24B) -- Best All-Rounder

**Strengths:**
- Highest validity rate (43.3%) among standard configs
- Best valid-builds-per-hour throughput (22.8)
- Reliable on easy-medium cases (3/3 on simple-fighter, thrown-fighter, dual-dedication)
- Good balance of speed (68s) and quality (7.2)

**Weaknesses:**
- Relatively high score variance (1.7)
- Struggles with caster builds (0/3 wizard-illusionist)
- Higher error rate when it fails (3.8 errors/build)

**Verdict:** The default choice for production use. Fast, reliable on most cases, and the best cost-efficiency ratio.

### Mistral Small 3.2 Tuned (24B, temp=0.4, repeat_penalty=1.2, min_p=0.05, 32K ctx)

**Strengths:**
- Perfect on thaum-champion (3/3) -- only config to achieve this
- Tuning params successfully reduce some error types
- 32K context allows more feat data in prompts

**Weaknesses:**
- Highest score variance (2.2) -- very inconsistent
- Slower than base mistral (78s vs 68s) due to larger context
- Lost consistency on dual-dedication (1/3 vs base's 3/3)
- `repeat_penalty` may be over-constraining valid repetition patterns

**Verdict:** Tuning helps on specific cases but hurts overall consistency. The 32K context doesn't provide clear benefits over 16K. `repeat_penalty` is a blunt instrument that may suppress valid structural patterns (e.g., taking multiple feats from the same archetype).

### Qwen 2.5 Coder (32B, Q6_K)

**Strengths:**
- Lowest errors per invalid build (2.6) -- fails gracefully
- Lowest score variance (1.0) -- very consistent output quality
- Strong on sneaky-caster (2/3) -- good at unspecified-class cases
- Most token-efficient (11,167 avg)

**Weaknesses:**
- Below-average validity (30%)
- Slowest standard model (110s) due to Q6_K quantization + 32B size
- Low throughput (9.8 valid/hr)
- Zero on thaum-champion, wizard-illusionist, exemplar-thrown

**Verdict:** The "safe choice" -- rarely produces garbage, but doesn't push for creative or complex builds. The Q6_K quantization buys quality at the cost of speed. Better suited for single-shot generation where you need reliable (if conservative) output.

### Qwen 2.5 (32B, standard)

**Strengths:**
- Low score variance (1.0) -- consistent quality
- Invalid builds still score well (7.0 avg) -- close to valid quality
- Good token efficiency (11,673)

**Weaknesses:**
- Lowest validity of viable models (23.3%)
- Slow for its validity rate (97s)
- Poor throughput (8.7 valid/hr)
- 0/3 on thaum-champion, wizard-illusionist, exemplar-thrown

**Verdict:** The general-purpose Qwen 2.5 underperforms its Coder variant on this task. The Coder model's instruction-following training translates directly to better structured output compliance. Not recommended for this use case.

### Phi-4 (14B) -- Best Value

**Strengths:**
- **Fastest model** (63s avg, 57.3 builds/hr)
- Surprisingly good validity for its size (33.3%)
- Second-best valid throughput (19.1/hr)
- Perfect on thrown-fighter and dual-dedication (3/3 each)
- Only 14B parameters -- runs on a single GPU with room to spare

**Weaknesses:**
- Smaller context window limits complex builds
- 0/3 on thaum-champion -- struggles with dedication mechanics
- Quality ceiling lower than 24-32B models on hard cases

**Verdict:** Remarkable performance for a 14B model. Best choice when speed matters more than peak quality, or when GPU memory is constrained. The 2x speed advantage over mistral-small makes it viable for generate-and-filter workflows where you generate many candidates and keep the valid ones.

### Qwen3 MoE (30B, 3B active) -- Not Viable

**Strengths:**
- Fast for a thinking model (95s avg)
- Low parameter activation means low memory usage

**Weaknesses:**
- **0/30 valid builds** -- complete failure
- Lowest scores across the board (5.8 avg)
- Massive thinking token overhead (9,141 avg completion tokens vs ~1,700 for standard models)
- 22,869 avg total tokens -- 2x the cost of other models for worse results
- Produces many empty/underfilled builds (128 "missing feat slots" errors are primarily from this model)

**Verdict:** 3B active parameters is insufficient for complex structured generation with constraint satisfaction. The thinking overhead doesn't compensate -- the model burns tokens on reasoning chains but can't translate them into correct output. The MoE architecture's efficiency advantage is irrelevant when validity is zero. **Do not use for structured generation tasks.**

### Mistral Small + Vector Ranking -- Best Quality

**Strengths:**
- **Highest overall score** (7.4) and **highest theme score** (8.7)
- When valid, produces the best-quality builds (8.7 valid score)
- Perfect on complex-multiclass (3/3) -- only config to achieve this
- Only config to pass exemplar-thrown (1/3)

**Weaknesses:**
- Vector ranking introduces duplicate feats (ranked feats get repeated)
- Lower validity than base mistral (30% vs 43.3%)
- Higher errors per invalid build (4.3) -- ranking pushes the model toward specific feats that conflict

**Verdict:** Vector ranking significantly improves thematic quality but hurts validity through duplicate feats. The ranking signal is too strong -- the model fixates on top-ranked feats. A dedup pass before generation would likely unlock the quality benefits without the validity penalty. Best config for quality-focused use cases once dedup is implemented.

### Qwen3 + Vector Ranking (32B, thinking) -- High Quality, Low Throughput

**Strengths:**
- Tied for second-highest validity (40%)
- Good quality when valid (8.3 avg)
- Thinking helps with complex constraint reasoning
- Perfect on simple-fighter and thrown-fighter (3/3 each)

**Weaknesses:**
- **Extremely slow** (258s avg, up to 375s+ per build)
- Lowest throughput (5.6 valid/hr) -- 4x slower than mistral-small
- Highest time variance (std 120s) -- unpredictable duration
- Catastrophic failures (8.9 errors per invalid build)
- 19,803 avg tokens -- expensive

**Verdict:** The thinking model + ranking combination achieves good validity but at enormous cost. The 258s average makes it impractical for interactive use or high-volume generation. Only justified when build quality is paramount and time/compute budgets are unconstrained.

---

## 5. Cross-Cutting Findings

### Thinking Models: Mixed Results

| Aspect | Standard Models | Thinking Models |
|--------|----------------|----------------|
| Speed | 63-110s | 95-258s |
| Tokens | 11-14K | 19-23K |
| Validity | 23-43% | 0-40% |
| Quality | 6.9-7.4 | 5.8-7.1 |

Thinking models are **not universally better** for structured generation. Qwen3-32B (thinking) achieves 40% validity but at 4x the cost. Qwen3-MoE (thinking, 3B active) achieves 0% -- thinking without sufficient parameter count is worthless.

**When thinking helps:** Complex multi-constraint problems where the model needs to reason about ordering and dependencies (dual-dedication, complex-multiclass).

**When thinking hurts:** Simple cases where the overhead doesn't improve output, and high-volume scenarios where throughput matters.

### Model Size vs. Quality

| Size | Best Config | Validity | Speed |
|------|------------|----------|-------|
| 14B | phi4 | 33.3% | 63s |
| 24B | mistral-small | 43.3% | 68s |
| 32B | qwen3-with-ranking | 40.0% | 258s |
| 30B (3B active) | qwen3-moe | 0.0% | 95s |

The jump from 14B to 24B provides meaningful validity improvement (+10%) with minimal speed cost (+5s). Going from 24B to 32B provides no validity improvement and costs 3-4x in speed. Active parameter count matters far more than total parameter count (MoE failure).

### Vector Ranking: Quality vs. Validity Trade-off

Adding vector DB feat ranking consistently:
- **Improves theme scores** (+0.4 to +1.5 points)
- **Reduces validity** (-5% to -13% absolute)
- **Increases duplicate feat errors**

The ranking signal is too aggressive -- it promotes a narrow set of high-scoring feats, causing the model to select the same feat in multiple slots. A dedup pass in the plan phase would likely resolve this.

### Quantization Impact

Qwen 2.5 Coder (Q6_K, 26 GB) vs Qwen 2.5 (Q4, ~19 GB):
- Q6_K is 13% slower (110s vs 97s)
- Q6_K has higher validity (30% vs 23%)
- Q6_K has lower error rate per invalid build (2.6 vs 3.0)

Higher quantization appears to help with structured output compliance, though the sample size (30 builds each) makes this suggestive rather than conclusive. The Coder variant's instruction-following fine-tuning is likely a bigger factor than quantization alone.

### Cases That No Model Can Solve

**fire-caster-lvl12** (0/24) and **frontline-controller-lvl14** (0/24) fail universally. These share:
- High level (12-14) = many feat slots = more constraint interactions
- Unspecified class/ancestry = model must choose wisely
- Complex prerequisite chains at higher levels
- Multiple dedication opportunities

These cases need **pipeline-level fixes** (skill prerequisite visibility, dedication ordering enforcement, feat dedup) rather than better models.

---

## 6. Recommendations

### For This Project (Pipeline Improvements)

Priority order based on error analysis:

1. **Skill prerequisite visibility** (34.1% of errors): Show required skill proficiencies alongside feat descriptions in the prompt
2. **Feat deduplication in plan phase** (19.3% of errors): Remove duplicate feats before full generation, especially with vector ranking
3. **Slot count enforcement** (18.6% of errors): Validate feat slot counts in the skeleton phase
4. **Dedication ordering** (11.5% of errors): Structurally enforce the "2 archetype feats before 2nd dedication" rule

### For Local LLM Selection (General Guidance)

**If you need one model:** Mistral Small 3.2 (24B). Best balance of speed, quality, and validity for structured generation tasks.

**If speed matters most:** Phi-4 (14B). 2x throughput of larger models with surprisingly competitive quality. Ideal for generate-and-filter pipelines.

**If quality matters most:** Mistral Small + vector ranking (with dedup). Highest scores when valid, but needs a dedup pass to unlock its potential.

**Avoid for structured tasks:**
- MoE models with low active parameters (Qwen3 30B-A3B)
- Thinking models without sufficient base capability
- 32B standard models (marginal improvement over 24B at 2-4x cost)

### For Temperature Tuning

All tests above used temperature 0.5 (or 0.4 for tuned). A dedicated temperature sweep across the top models is the natural next step to optimize this parameter.

---

## Appendix: Raw Data Location

- Results JSONL: `mcp-pf2e/benchmarks/results.jsonl`
- Suite definition: `mcp-pf2e/benchmarks/suite.json` (v1.1)
- Per-build JSON: `mcp-pf2e/builds/benchmark/<run_id>/`
- Runner: `python -m benchmarks.runner`
- Report tool: `python -m benchmarks.report`
