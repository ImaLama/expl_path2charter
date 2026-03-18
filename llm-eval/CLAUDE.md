# CLAUDE.md — LLM Evaluation Framework (llm-eval)

## Project Overview
A generalized, domain-agnostic LLM evaluation framework that tests multiple models
(cloud and local) against configurable challenge packs, then scores results using
LLM-as-judge evaluation with positional bias detection.

Originally designed for Pathfinder 2e character generation testing, refactored into
a reusable framework with swappable challenge packs.

## Origin
This project was designed in Claude.ai and is being implemented via Claude Code.
The full design spec is in `SPEC.md`. Implementation instructions are in `QUICKSTART.md`.
The existing PF2e-specific prototype is in `prototype/` — use it as reference for
working API call patterns and judge logic, but rewrite the architecture to match the spec.

## Architecture
```
llm-eval/
├── CLAUDE.md              ← you are here
├── QUICKSTART.md          ← implementation instructions (read first)
├── SPEC.md                ← full design spec
├── README.md              ← user-facing docs
├── requirements.txt
├── .env.example
│
├── prototype/             ← working PF2e-specific code (reference only)
│   ├── test_chargen.py    ← port provider/API logic to llm_eval/providers.py
│   ├── score_chargen.py   ← port judge/scoring logic to llm_eval/judge.py
│   └── README.md
│
├── llm_eval/              ← core framework (domain-agnostic, NEVER domain-specific)
│   ├── __init__.py
│   ├── types.py           ← dataclasses, ChallengePack ABC, AutoScorer ABC
│   ├── providers.py       ← provider configs, availability checks, API calls
│   ├── discovery.py       ← pack discovery (scan packs/*/pack.py)
│   ├── runner.py          ← runs challenges across providers
│   ├── judge.py           ← LLM-as-judge scoring + head-to-head bias detection
│   └── report.py          ← generates markdown comparison reports
│
├── packs/                 ← challenge packs (each is self-contained)
│   ├── _template/         ← copy this to create a new pack
│   │   ├── pack.py
│   │   └── README.md
│   ├── starter/           ← generic pack for framework testing (Phase 1)
│   │   └── pack.py
│   ├── pf2e/              ← Pathfinder 2e character generation (Phase 2)
│   │   └── pack.py
│   └── coding/            ← coding challenges with auto-scorer (Phase 2)
│       └── pack.py
│
├── results/               ← output directory (gitignored)
├── tests/
└── cli.py                 ← main entry point
```

## Two-phase build approach

**Phase 1 — Generic framework:** Build llm_eval/ + cli.py + starter pack.
The framework is complete when you can run, score, compare, and report using
the starter pack with zero domain-specific code in the framework.

**Phase 2 — Domain packs:** Drop in pf2e, coding, or any other pack.
No changes to llm_eval/ should be needed. If they are, that's a design smell.

## Key Design Decisions
- Framework is domain-agnostic — all domain logic lives in packs
- Challenge packs are Python modules with a standard interface (ChallengePack ABC)
- All providers use OpenAI-compatible SDK where possible; Anthropic uses its own SDK
- Local models go through Ollama's OpenAI-compatible API
- Judge scoring uses structured JSON output with pack-defined rubrics
- Head-to-head comparisons run twice with reversed order for bias detection
- Results include full content (needed by scorer) — stored as JSON
- Reports are markdown with tables

## Conventions
- Python 3.11+, type hints on all public functions
- dataclasses for structured data (not Pydantic — keep deps light)
- pytest for tests
- CLI uses argparse (no click/typer dependency)
- All file I/O uses pathlib
- Generation temperature: 0.7 / Judge temperature: 0.2

## Current Status
Phase 1 complete — framework is functional end-to-end.

## What's Been Built
- [x] Design spec (SPEC.md)
- [x] Implementation instructions (QUICKSTART.md)
- [x] Template pack interface (packs/_template/)
- [x] Prototype reference code (prototype/)
- [x] Phase 1 Step 1: types.py — all dataclasses + ABCs
- [x] Phase 1 Step 2: providers.py — all cloud + local providers, retry logic
- [x] Phase 1 Step 3: discovery.py + starter pack (4 prompts, 3 criteria)
- [x] Phase 1 Step 4: runner.py + cli.py (list-providers, list-packs, run, score, new-pack)
- [x] Phase 1 Step 5: judge.py — individual scoring with rubric-driven prompts
- [x] Phase 1 Step 6: report.py — markdown tables + JSON scores
- [x] Phase 1 Step 7: head-to-head bias detection (built into judge.py)
- [x] Phase 1 Step 8: combined run+score via --score flag, new-pack scaffolding
- [ ] Phase 2 Pack A: pf2e
- [ ] Phase 2 Pack B: coding
- [ ] Tests

## Known Constraints
- Ollama auto-detection needs httpx for health checks
- Some providers (Gemini) have rate limits on free tier — runner should handle retries
- Code execution in coding pack AutoScorer must be sandboxed (subprocess, timeout, tempfile)
