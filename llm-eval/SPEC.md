# SPEC.md — LLM Evaluation Framework Design Specification

## 1. Purpose

A CLI tool that evaluates LLM quality across arbitrary domains by:
1. Running the same prompts against multiple LLM providers (cloud + local)
2. Scoring results via LLM-as-judge with structured rubrics
3. Optionally scoring results via automated validators (e.g. code execution)
4. Generating ranked comparison reports

The framework is domain-agnostic. Domain-specific logic lives in **challenge packs**.

---

## 2. Core Framework (`llm_eval/`)

No domain-specific code belongs here. If you need to write "if pack.name == ..."
in this layer, the pack interface needs extending instead.

### 2.1 `types.py` — Shared Data Structures

Use Python dataclasses. Key types:

```python
@dataclass
class ProviderConfig:
    key: str                    # e.g. "gemini", "ollama-qwen32b"
    name: str                   # human-readable, e.g. "Google Gemini 2.5 Pro"
    model: str                  # model string sent to API
    tier: str                   # "free", "local", "$5 prepaid", etc.
    base_url: str | None        # OpenAI-compatible endpoint (None for Anthropic)
    env_key: str | None         # env var name for API key (None for Ollama)
    native_sdk: str | None      # "anthropic" if it uses its own SDK, else None

@dataclass
class Prompt:
    key: str                    # e.g. "goblin-inventor"
    label: str                  # human description
    content: str                # the actual prompt text
    difficulty: str             # "easy", "medium", "hard" (for reporting)
    metadata: dict              # pack-specific extra data (e.g. test cases for coding)

@dataclass
class GenerationResult:
    provider: str
    model: str
    name: str
    tier: str
    prompt_key: str
    prompt_label: str
    content: str                # the raw model output
    elapsed_s: float
    input_tokens: int | None
    output_tokens: int | None
    error: str | None           # None if success

@dataclass
class ScoreCriterion:
    key: str                    # e.g. "rule_legality"
    label: str                  # e.g. "Rule Legality"
    description: str            # what the judge should evaluate
    weight: float               # 0.0 to 1.0, all weights in a rubric must sum to 1.0

@dataclass
class Rubric:
    criteria: list[ScoreCriterion]
    judge_preamble: str         # domain context for the judge (e.g. "You are a PF2e expert")
    output_schema: dict         # JSON schema the judge should return per criterion

@dataclass
class IndividualScore:
    provider: str
    model: str
    name: str
    prompt_key: str
    scores: dict                # criterion_key -> {score: int, ...extra fields}
    weighted_total: float       # computed from scores + rubric weights
    auto_scores: dict | None    # from automated validator, if any
    elapsed_s: float | None
    output_tokens: int | None

@dataclass
class HeadToHeadResult:
    prompt_key: str
    provider_a: str
    provider_b: str
    round_1_winner: str         # "A", "B", or "tie"
    round_2_winner: str         # reversed order result (mapped back to original)
    final_winner: str           # provider key or "tie"
    consistency: str            # "consistent" or "inconsistent"
    reasoning: str
```

**Abstract base classes:**

```python
from abc import ABC, abstractmethod

class ChallengePack(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def get_prompts(self) -> list[Prompt]: ...

    @abstractmethod
    def get_rubric(self) -> Rubric: ...

    def get_auto_scorer(self) -> 'AutoScorer | None':
        return None

    def get_system_prompt(self) -> str | None:
        return None


class AutoScorer(ABC):
    @abstractmethod
    def score(self, prompt: Prompt, result: GenerationResult) -> dict:
        """Returns {criterion_key: {score: int, details: str}}."""
        ...
```

### 2.2 `providers.py` — Provider Registry & API Calls

**Responsibilities:**
- Define all known providers (cloud + local) as ProviderConfig instances
- Check provider availability (API key present? Ollama model pulled?)
- Make API calls with retry logic and timeout handling
- Normalize responses into GenerationResult

**Cloud providers:**
- `gemini` — Gemini 2.5 Pro, OpenAI-compatible
- `deepseek` — DeepSeek V3.2, OpenAI-compatible
- `xai` — Grok 4.1, OpenAI-compatible
- `openai` — GPT-5.2, OpenAI-compatible
- `anthropic` — Claude Opus 4.6, native SDK

**Local providers (Ollama, auto-detected):**
- `ollama-qwen32b` — Qwen 2.5 32B Q5_K_M
- `ollama-qwen72b` — Qwen 2.5 72B Q4_K_M
- `ollama-llama70b` — Llama 3.1 70B Q4_K_M
- `ollama-nemo` — Mistral Nemo 12B
- `ollama-mixtral` — Mixtral 8x7B
- `ollama-deepseek32b` — DeepSeek-R1 32B

**Key implementation details:**
- Ollama URL from env `OLLAMA_BASE_URL`, default `http://localhost:11434/v1`
- Ollama model availability checked via `GET {base}/api/tags`
- Default generation: `temperature=0.7`, `max_tokens=4096`
- Default judge: `temperature=0.2`, `max_tokens=2048`
- Retry on transient errors (3 attempts, 2s backoff)
- Timeout: 120s for cloud, 300s for local (large models are slow)

**Public functions:**
```python
def get_all_providers() -> dict[str, ProviderConfig]: ...
def list_available() -> list[tuple[str, ProviderConfig, bool, str]]: ...
    # Returns (key, config, is_available, reason)
def call_provider(config: ProviderConfig, prompt: str, system_prompt: str | None,
                  temperature: float = 0.7, max_tokens: int = 4096) -> GenerationResult: ...
```

### 2.3 `discovery.py` — Pack Discovery

Scan `packs/*/pack.py` for modules that export a `get_pack()` function
returning a ChallengePack instance. Directories starting with `_` are skipped.

```python
def discover_packs() -> list[ChallengePack]: ...
def get_pack_by_name(name: str) -> ChallengePack | None: ...
```

### 2.4 `runner.py` — Challenge Runner

**Responsibilities:**
- Accept a list of providers and a challenge pack
- Run each prompt from the pack against each provider
- Handle failures gracefully (log error, continue to next)
- Save results as JSON (full content included)
- Save individual outputs as markdown files
- Print progress to terminal with timing

**Function signature:**
```python
def run_challenges(
    providers: list[str],
    pack: ChallengePack,
    output_dir: Path,
    prompt_keys: list[str] | None = None,  # None = all prompts
) -> list[GenerationResult]:
```

**Output files:**
```
results/<timestamp>_<pack_name>/
├── results.json                          # all GenerationResult objects (with content)
├── summary.json                          # same but without content field
├── <prompt_key>_<provider>.md            # individual outputs for human reading
└── ...
```

### 2.5 `judge.py` — LLM-as-Judge Scoring Engine

**Individual scoring flow:**
1. For each GenerationResult, build a judge prompt from the pack's rubric:
   - The rubric's judge_preamble (domain context)
   - Each criterion's description and scoring guidance
   - The original prompt given to the model
   - The model's output (NO provider identity — blind evaluation)
   - The expected JSON output schema from the rubric
2. Call judge model with `temperature=0.2`
3. Parse JSON response (strip markdown fences, find JSON boundaries)
4. Validate it has all expected criterion keys
5. Compute weighted_total from criterion scores × weights
6. If the pack provides an AutoScorer, run it and attach auto_scores

**Head-to-head flow:**
1. For each pair of providers within a prompt, build a comparison prompt
   using the pack's rubric for context
2. Run TWICE with reversed presentation order
3. Same winner both rounds → confident result
4. Different winners → "tie (positional bias detected)"

**Merging auto_scores and judge_scores:**
When a pack has an AutoScorer, the final weighted_total is a blend:
- The pack defines `auto_score_weight` (e.g. 0.5 for coding)
- `final = (judge_weighted × (1 - auto_weight)) + (auto_weighted × auto_weight)`
- Packs without an AutoScorer: final = judge_weighted (auto_weight = 0)

To support this, add to the ChallengePack ABC:
```python
def get_auto_score_weight(self) -> float:
    """Weight of auto-scorer in final score (0.0 to 1.0). Default 0."""
    return 0.0
```

**Public functions:**
```python
def score_individual(
    results: list[GenerationResult],
    pack: ChallengePack,
    judge_provider: str,
) -> list[IndividualScore]: ...

def score_head_to_head(
    results: list[GenerationResult],
    pack: ChallengePack,
    judge_provider: str,
) -> list[HeadToHeadResult]: ...
```

### 2.6 `report.py` — Report Generator

**Generates a markdown report with:**
1. Test metadata (date, judge model, pack name, providers tested)
2. Per-prompt score tables (all criteria + weighted total + time + tokens)
3. Flagged issues per provider (from judge notes)
4. Aggregate rankings across all prompts (average weighted score)
5. Head-to-head results and win tally (if applicable)
6. Auto-score breakdown (if pack has an AutoScorer)

**Also saves a machine-readable JSON with all scores.**

```python
def generate_report(
    scores: list[IndividualScore],
    head_to_head: list[HeadToHeadResult] | None,
    pack: ChallengePack,
    judge_provider: str,
    output_dir: Path,
) -> Path:  # returns path to markdown report
```

---

## 3. CLI (`cli.py`)

Single entry point with subcommands:

```
python cli.py list-providers              # Show available providers
python cli.py list-packs                  # Show available challenge packs
python cli.py run <pack> [options]        # Generate + optionally score
python cli.py score <results.json> [opts] # Score existing results
python cli.py new-pack <name>             # Scaffold a new challenge pack
```

### `run` subcommand
```
python cli.py run starter
python cli.py run starter --providers gemini deepseek ollama-qwen32b
python cli.py run starter --prompt-keys easy-recursion hard-branch-predictor
python cli.py run starter --score --judge gemini
python cli.py run starter --score --judge gemini --head-to-head
```

Options:
- `pack` (positional) — name of the challenge pack
- `--providers` — limit to specific providers (default: all available)
- `--prompt-keys` — limit to specific prompts (default: all in pack)
- `--score` — also run scoring after generation
- `--judge` — judge model for scoring (default: gemini)
- `--head-to-head` — include pairwise comparisons
- `--output-dir` — results directory (default: `results/`)

### `score` subcommand
```
python cli.py score results/20250318_starter/results.json
python cli.py score results/20250318_starter/results.json --judge anthropic --head-to-head
```

### `new-pack`
```
python cli.py new-pack trivia
# Copies packs/_template/ to packs/trivia/, prints next steps
```

---

## 4. Challenge Pack Interface

Each pack is a Python package in `packs/<name>/` with a `pack.py` that
exports a `get_pack()` function returning a ChallengePack instance.

### 4.1 Required files

```
packs/my_pack/
├── pack.py        # must export get_pack() -> ChallengePack
└── README.md      # description, prompt rationale, rubric explanation
```

### 4.2 Discovery

Framework scans `packs/*/pack.py`, imports each, calls `get_pack()`.
Directories starting with `_` are excluded.

### 4.3 The AutoScorer contract

Packs that return a non-None AutoScorer must also return a meaningful
`get_auto_score_weight()` (e.g. 0.5). The AutoScorer's `score()` method
returns a dict of `{criterion_key: {score: 1-5, details: str}}`.

The framework handles merging — the pack never touches judge scores.

---

## 5. Challenge Pack: PF2e (`packs/pf2e/`) — Phase 2

Port from prototype. Contains:
- 4 prompts (goblin-inventor, elf-wizard-simple, vague-concept, multiclass-tank)
- System prompt establishing the PF2e expert builder role
- Rubric with 5 criteria: rule_legality (30%), completeness (20%),
  concept_fidelity (20%), mechanical_cohesion (15%), creativity (15%)
- Judge preamble instructs judge to flag fabricated PF2e content
- No auto-scorer (all LLM-judged)

---

## 6. Challenge Pack: Coding (`packs/coding/`) — Phase 2

### 6.1 Prompts
Each prompt includes visible examples + hidden test cases in metadata.

Difficulty range:
- Easy: string reversal, FizzBuzz variant
- Medium: LRU cache, longest palindromic substring
- Hard: regex engine, N-Queens solver

### 6.2 Rubric (LLM-judged, 50% of total)

| Criterion | Weight | Description |
|-----------|--------|-------------|
| code_quality | 35% | Clean, readable, idiomatic |
| approach | 30% | Algorithm choice, efficiency reasoning |
| edge_cases | 20% | Handles edge cases, input validation |
| explanation | 15% | Clear explanation of approach and complexity |

### 6.3 AutoScorer (automated, 50% of total)

1. Extract code from response (find code fences)
2. Write to temp file
3. Run against test cases in subprocess with timeout (10s)
4. Score:
   - `executes`: runs without error? (0 or 5)
   - `correctness`: % test cases passing (scaled 1-5)
   - `performance`: completes within time limit? (pass/fail note)

**SAFETY:** subprocess.run() with timeout, tempfile isolation, no eval/exec,
catch all exceptions (crash = score 0).

### 6.4 Score merging

`get_auto_score_weight()` returns 0.5.
Final = (judge_weighted × 0.5) + (auto_weighted × 0.5)

---

## 7. Challenge Pack: Template (`packs/_template/`) — Reference

Minimal skeleton users copy to create their own pack. Contains:
- Skeleton ChallengePack subclass with comments
- 2 placeholder prompts
- Generic 3-criterion rubric (accuracy, completeness, clarity)
- No auto-scorer
- README explaining how to customize

---

## 8. Testing Strategy

### Unit tests (`tests/`)
- `test_types.py` — dataclass construction, rubric weight validation
- `test_providers.py` — mock API calls, response normalization, availability checks
- `test_discovery.py` — pack scanning, template exclusion
- `test_judge.py` — mock judge responses, JSON parsing, weighted scores, bias detection
- `test_report.py` — report generation with sample data
- `test_coding_autoscorer.py` — code extraction, sandboxed execution, scoring

### Integration tests (require API keys)
- `test_integration.py` — end-to-end with one real provider (gemini, free tier)
  Mark with `@pytest.mark.integration` so they can be skipped

---

## 9. Dependencies

Keep minimal:
```
openai>=1.0
anthropic>=0.40
python-dotenv
httpx
```

Dev:
```
pytest
```

No heavy frameworks. This is a CLI tool.
