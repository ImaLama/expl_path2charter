# Session Summary — 2026-04-23

## What Was Done

### 1. Model Setup
- Pulled `qwen3:30b-a3b` (18 GB MoE model, 3B active params)
- `phi4:14b` was already pulled in previous session
- Skipped `gemma3:27b` (not downloaded, excluded from this session's runs)

### 2. Code Changes (committed as 8961082)
Expanded benchmark suite from 3 to 9 configs and improved pipeline:

- **suite.json v1.1**: Added configs for mistral-small-tuned, qwen25, gemma3, phi4, qwen3-moe; renamed old config IDs for clarity
- **pipeline.py**: Added 3 new model keys (gemma3, phi4, qwen3-30b-a3b, qwen25), wired `ollama_options` through all LLM call sites, bumped default context 8K→16K, injected class-granted skills as mandatory
- **prompt_builder.py**: Locked class/ancestry in JSON schema enums (prevents identity drift), added dedication instructions to plan prompt
- **runner.py**: Added `ollama_options` passthrough
- **cli.py**: Added `--num-ctx` and `--repeat-penalty` CLI flags
- **report.py**: Multi-run aggregation (pass rates, mean scores, per-case score arrays), improved compare view

### 3. Benchmark Run 2026-04-23_001
Ran 50 builds (10 cases × 5 configs × 1 run) as a validation round with known-good models:

| Config               | Valid | Avg Time | Overall |
|----------------------|-------|----------|---------|
| mistral-small        | 4/10  |     80s  |     7.0 |
| mistral-small-tuned  | 6/10  |     79s  |     6.8 |
| qwen25-coder         | 4/10  |    110s  |     7.0 |
| mistral-with-ranking | 2/10  |     73s  |     7.1 |
| qwen3-with-ranking   | 5/10  |    213s  |     6.9 |

Full analysis in `mcp-pf2e/benchmarks/benchmark-2026-04-23-001.md`.

## What's Next

### Immediate (next session)
1. **Run untested models** — one round each for: `qwen25`, `phi4`, `qwen3-moe`
   - Verify they work technically (produce valid JSON, complete without errors)
   - Skip `gemma3` (not downloaded)
2. **If all models pass technical check** — run 2× repeat builds for all models (achieving 3 total builds per case per model for variance analysis)

### Pipeline Fixes (priority order from benchmark findings)
1. **Skill prerequisite visibility** — #1 error source (39% of errors). Two-pronged approach:
   - **"Costs visible" display**: Show feat prereqs inline (e.g., "Quick Identification [requires: trained Arcana]") so the model sees the skill cost when selecting feats. Higher leverage, covers 50 errors.
   - **Validate plan against allocated skills** before moving to full generation — catch mismatches early.
2. **Feat-chain bundling** — Bundle feats with their feat-prereqs as packages (e.g., "Adaptive Adept" always includes "Adapted Cantrip"). Clean for feat→feat chains (8 errors). Don't bundle skill prereqs into packages — those have resource competition (shared skill slots, "or" branches) that makes bundling complex.
3. **Duplicate feat dedup in plan phase** — especially with vector ranking enabled (22% of errors)
4. **Dedication ordering enforcement** — structural constraint that models can't reason about in one pass (14% of errors)

### Tuning
- `mistral-small-tuned` (60% valid) is the best config so far — explore similar tuning for other models
- Vector ranking boosts theme but hurts validity via duplicates — needs dedup before ranking signal is useful
