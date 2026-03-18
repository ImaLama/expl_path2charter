# QUICKSTART — Instructions for Claude Code

This file tells you (Claude Code) how to implement this project. Read it first,
then read CLAUDE.md and SPEC.md before writing any code.

## Context

This project was designed in Claude.ai. The design is complete — your job is
implementation. All architecture decisions have been made. The spec is in SPEC.md.

**Critical principle:** The framework is domain-agnostic. It knows nothing about
Pathfinder, coding challenges, or any specific domain. All domain logic lives in
challenge packs. Build and verify the entire framework BEFORE creating any
domain-specific packs.

## What exists already

```
CLAUDE.md          — Project memory (update this as you work)
SPEC.md            — Full design spec (the source of truth)
README.md          — User-facing docs (update as features land)
.env.example       — API key template
.gitignore
requirements.txt   — Python dependencies

prototype/         — Working PF2e-specific code (reference implementation)
  test_chargen.py  — generation harness with cloud + local providers
  score_chargen.py — LLM-as-judge scorer with bias detection
  README.md

packs/_template/
  pack.py          — template pack showing the ChallengePack interface

llm_eval/          — empty, needs implementation
tests/             — empty, needs tests
```

## Reading order

1. This file (QUICKSTART.md) — understand the approach
2. CLAUDE.md — project context and conventions
3. SPEC.md §1-4 — core framework design (types, providers, runner, judge, report)
4. packs/_template/pack.py — understand the pack interface
5. prototype/test_chargen.py — working API call patterns to port
6. prototype/score_chargen.py — working judge logic to port
7. SPEC.md §5-7 — domain pack designs (read when you reach Phase 2)

---

# PHASE 1 — Generic Framework

Build the complete framework using ONLY the template pack for testing.
No PF2e, no coding challenges. Just the engine.

The template pack has simple generic prompts ("explain recursion",
"compare dining philosophers solutions") that are enough to verify
every part of the pipeline works.

## Step 1: Types

Implement `llm_eval/types.py` with all dataclasses and abstract base classes.
See SPEC.md §2.1 for the full list:
- ProviderConfig, Prompt, GenerationResult
- ScoreCriterion, Rubric, IndividualScore, HeadToHeadResult
- ChallengePack (ABC), AutoScorer (ABC)

**Verify:**
```bash
python -c "from llm_eval.types import ChallengePack, Prompt, Rubric; print('Types OK')"
```

## Step 2: Providers

Implement `llm_eval/providers.py`. Port the API call logic from
`prototype/test_chargen.py`. This file does three things:
1. Defines all provider configs (cloud + local/Ollama)
2. Checks provider availability (API key set? Ollama model pulled?)
3. Makes API calls and returns GenerationResult

Port all providers from the prototype: gemini, deepseek, xai, openai,
anthropic, and all the ollama-* local models. Keep the Anthropic native SDK
handling — it's different from the OpenAI-compatible providers.

**Verify:**
```bash
python -c "from llm_eval.providers import list_available; print(list_available())"
```
Should show which providers have API keys or Ollama models available.

## Step 3: Pack discovery + starter pack

Implement pack discovery in `llm_eval/discovery.py`: scan `packs/*/pack.py`
for modules that export a `get_pack()` function returning a ChallengePack
instance. Skip directories starting with `_` (like `_template`).

Copy `packs/_template/` to `packs/starter/` and rename the class. This is
your first real pack — the one you'll use to test the entire framework.

Flesh out the starter pack with 3-4 generic knowledge prompts at varying
difficulty:

- easy: "Explain the concept of recursion in 3 sentences."
- easy: "What is the difference between a stack and a queue?"
- medium: "Compare three approaches to solving the dining philosophers
  problem. Include pseudocode and trade-off analysis."
- hard: "Explain how a modern CPU branch predictor works, covering
  static prediction, dynamic prediction with BHT, and the performance
  implications of branch misprediction in pipelined architectures."

The rubric should be generic: accuracy (40%), completeness (35%),
clarity (25%). The template already has this.

**Verify:**
```bash
python -c "
from llm_eval.discovery import discover_packs
packs = discover_packs()
for p in packs:
    print(f'{p.name}: {len(p.get_prompts())} prompts, {len(p.get_rubric().criteria)} criteria')
"
```
Should show the starter pack.

## Step 4: Runner + minimal CLI

Implement `llm_eval/runner.py` — runs prompts from a pack against providers.
See SPEC.md §2.3 for the function signature and output file structure.

Implement `cli.py` with these subcommands:
- `list-providers` — show available providers with status
- `list-packs` — show discovered packs
- `run <pack>` — run a pack against providers

Use argparse. No click or typer.

**Verify:**
```bash
python cli.py list-providers
python cli.py list-packs
python cli.py run starter --providers gemini
# Should create results/<timestamp>_starter/ with results.json + markdown files
ls results/
```

This is the first end-to-end test. You should see actual LLM responses saved
to disk. If this works, the provider layer + runner + CLI are all working.

## Step 5: Judge (individual scoring)

Implement `llm_eval/judge.py` — the LLM-as-judge scoring engine.
Port the judge prompt construction and JSON parsing from
`prototype/score_chargen.py`.

Key details:
- Build the judge prompt dynamically from the pack's rubric
  (criteria descriptions, scoring guidance, output schema)
- Include the original prompt and the model's response (blind, no provider name)
- Call the judge with temperature=0.2 for consistency
- Parse JSON response with markdown fence stripping (the prototype has this)
- Compute weighted totals from criterion scores × rubric weights
- Warn if the judge model is also a contestant

Add `score` subcommand to CLI:
```
python cli.py score <results.json> --judge <provider>
```

**Verify:**
```bash
python cli.py run starter --providers gemini deepseek
python cli.py score results/<ts>_starter/results.json --judge gemini
# Should print per-criterion scores for each provider
```

## Step 6: Report

Implement `llm_eval/report.py` — generates a markdown comparison report.
See SPEC.md §2.5 for the report structure:
- Test metadata (date, judge, pack, providers)
- Per-prompt score tables
- Aggregate rankings across all prompts
- Flagged issues from judge notes

Reports should be saved as both markdown (human-readable) and
JSON (machine-readable).

**Verify:**
```bash
python cli.py score results/<ts>_starter/results.json --judge gemini
cat results/<ts>_starter/*_scores_*.md
# Should show formatted tables with rankings
```

## Step 7: Head-to-head with bias detection

Add pairwise head-to-head comparisons to `judge.py`.
Port the logic from `prototype/score_chargen.py`:
1. For each pair of providers within a prompt, build a comparison prompt
2. Run TWICE with reversed presentation order
3. If same winner both rounds → confident result
4. If different winners → "tie (positional bias detected)"

Add `--head-to-head` flag to the `score` subcommand.
Add head-to-head results and win tally to the report.

**Verify:**
```bash
python cli.py score results/<ts>_starter/results.json --judge gemini --head-to-head
# Report should now include pairwise comparisons section
```

## Step 8: Combined run+score and polish

Add `--score` and `--judge` flags to the `run` subcommand so you can
generate and score in one command:
```bash
python cli.py run starter --score --judge gemini --head-to-head
```

Add the `new-pack` subcommand:
```bash
python cli.py new-pack my_domain
# Should copy packs/_template/ to packs/my_domain/ and print instructions
```

Add retry logic for transient API failures (3 attempts, 2s backoff).
Add cost estimation to reports (based on token counts + known pricing).

**Verify the full pipeline end-to-end:**
```bash
python cli.py run starter --providers gemini deepseek --score --judge gemini --head-to-head
# Single command: generates, scores, compares, produces report
```

## PHASE 1 CHECKPOINT

At this point the framework is complete and domain-agnostic. Everything
works end-to-end with the starter pack. Verify by asking yourself:

- Can I list providers and packs?
- Can I run any pack against any available provider?
- Can I score results with any available judge?
- Does head-to-head bias detection work?
- Do reports show ranked tables?
- Can I create a new empty pack from the template?

If yes → update CLAUDE.md, commit, and move to Phase 2.

---

# PHASE 2 — Domain Packs

The framework is done. Now create domain-specific packs. Each pack is
completely independent — you can build them in any order.

**No changes to `llm_eval/` should be needed.** If a pack requires framework
changes, that's a design smell — reconsider the pack's approach first.

## Pack A: PF2e Character Generation (`packs/pf2e/`)

Port from prototype. See SPEC.md §5.

Create `packs/pf2e/pack.py` with:
- `name`: "pf2e"
- `description`: "Pathfinder 2e character generation"
- `get_system_prompt()`: establishes the PF2e expert builder role
- `get_prompts()`: 4 prompts from prototype/test_chargen.py:
  - goblin-inventor (hard): Level 5 Goblin Inventor
  - elf-wizard-simple (easy): Level 3 Elf Wizard
  - vague-concept (medium): "sneaky, poisons, nature"
  - multiclass-tank (hard): Level 8 Champion/Bard multiclass
- `get_rubric()`: 5 criteria from prototype/score_chargen.py:
  - rule_legality (30%)
  - completeness (20%)
  - concept_fidelity (20%)
  - mechanical_cohesion (15%)
  - creativity (15%)
- `get_auto_scorer()`: returns None (pure LLM-judged)

The rubric's judge_preamble should include PF2e-specific guidance:
instruct the judge to check for fabricated feats/features and flag them.

**Verify:**
```bash
python cli.py list-packs
# Should show both "starter" and "pf2e"
python cli.py run pf2e --providers gemini --prompt-keys elf-wizard-simple
python cli.py score results/<ts>_pf2e/results.json --judge gemini
```

## Pack B: Coding Challenges (`packs/coding/`)

The interesting one — has an AutoScorer. See SPEC.md §6.

Create `packs/coding/pack.py` with:
- 4-6 coding prompts at varying difficulty (see SPEC.md §6.1)
- A rubric for the LLM-judged portion (50% of total):
  code_quality (35%), approach (30%), edge_cases (20%), explanation (15%)
- An AutoScorer (50% of total) that:
  1. Extracts code from the response (find code fences)
  2. Writes to a temp file
  3. Runs against test cases in a sandboxed subprocess
  4. Scores: executes (binary), correctness (% test cases passed),
     performance (timeout check)

**SAFETY — non-negotiable for the AutoScorer:**
- Run code via subprocess.run() with timeout=10
- Use tempfile for isolation
- NEVER use eval() or exec() in the main process
- No network access from the subprocess
- Catch all exceptions — a crash is a score of 0, not a framework error

The framework's judge.py needs to handle the case where a pack returns
auto_scores: merge them with judge scores using the pack-defined weights.
This should already work if you implemented the AutoScorer interface
properly in Phase 1 — but this is the first time it gets exercised.

**If the framework needs changes to support AutoScorer:** that's acceptable,
but keep the changes generic. Don't add coding-specific logic to the
framework.

**Verify:**
```bash
python cli.py run coding --providers gemini deepseek --score --judge gemini
# Report should show both auto-scores and judge-scores merged
```

## Pack C: Your Own (`packs/whatever/`)

```bash
python cli.py new-pack trivia
# Edit packs/trivia/pack.py — add prompts and rubric
python cli.py run trivia --score --judge gemini
```

---

# Key principles

1. **Framework knows nothing about domains.** If you find yourself writing
   "if pack.name == 'coding'" in `llm_eval/`, you're doing it wrong.

2. **Port, don't reinvent.** The prototype code works. Reuse API call patterns,
   JSON parsing, and judge prompt templates. Refactor into the new structure.

3. **Test each step before moving on.** Every step has a verify command. Run it.
   Don't proceed if it fails.

4. **Keep deps minimal.** openai, anthropic, python-dotenv, httpx. Nothing else.

5. **Update CLAUDE.md** after completing each step with what was built,
   decisions made, and issues discovered.

---

# Important implementation notes

- The prototype's `test_chargen.py` has working API call code for ALL providers
  (cloud + Ollama local). Port all of it into `providers.py`.
- The prototype's `score_chargen.py` has the complete judge prompt templates,
  JSON parsing with markdown fence stripping, and the head-to-head bias
  detection logic. Port all of it into `judge.py`.
- Provider availability check for Ollama uses httpx GET to `{base}/api/tags`.
- Anthropic uses its own SDK, not OpenAI-compatible. The prototype handles this.
- Ollama URL defaults to `http://localhost:11434/v1`, configurable via
  `OLLAMA_BASE_URL` env var.
- Judge temperature should be 0.2 (low, for consistent scoring).
  Generation temperature should be 0.7 (from provider defaults).
