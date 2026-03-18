# llm-eval — Multi-LLM Evaluation Framework

Test any LLM (cloud or local) against structured challenges, score with LLM-as-judge, and generate ranked comparison reports.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env    # add your API keys

# See what's available
python cli.py list-providers
python cli.py list-packs

# Run the starter challenge pack
python cli.py run starter --score --judge gemini

# Run with head-to-head comparisons
python cli.py run starter --score --judge gemini --head-to-head

# Score existing results with a different judge
python cli.py score results/<timestamp>_starter/results.json --judge anthropic

# Create your own challenge pack
python cli.py new-pack trivia
```

## How It Works

**Generate:** The same prompt(s) are sent to every available provider. Results are saved as markdown (human-readable) and JSON (machine-readable).

**Score:** Each result is sent to a judge model (blind — no provider identity) with a structured rubric. The judge scores each criterion 1-5. Some packs also have automated scoring (e.g. the coding pack executes code against test cases).

**Report:** Scores are aggregated into a ranked comparison table. Optional head-to-head comparisons run each pairing twice with reversed order to detect positional bias.

## Providers

### Cloud
| Key | Model | Free? |
|-----|-------|-------|
| `gemini` | Gemini 2.5 Pro | Yes, 100 req/day |
| `deepseek` | DeepSeek V3.2 | 5M tokens free |
| `xai` | Grok 4.1 | $25 free credits |
| `openai` | GPT-5.2 | $5 prepaid |
| `anthropic` | Claude Opus 4.6 | $5 prepaid |

### Local (Ollama)
| Key | Model |
|-----|-------|
| `ollama-qwen32b` | Qwen 2.5 32B Q5_K_M |
| `ollama-qwen72b` | Qwen 2.5 72B Q4_K_M |
| `ollama-llama70b` | Llama 3.1 70B Q4_K_M |
| `ollama-nemo` | Mistral Nemo 12B |
| `ollama-mixtral` | Mixtral 8x7B |
| `ollama-deepseek32b` | DeepSeek-R1 32B |

## Challenge Packs

| Pack | Description | Auto-scorer? |
|------|-------------|-------------|
| `starter` | Generic knowledge prompts (framework testing) | No |
| `pf2e` | Pathfinder 2e character generation | No |
| `coding` | Programming challenges with test cases | Yes |

### Create Your Own

```bash
python cli.py new-pack my_domain
# Edit packs/my_domain/pack.py — define prompts, rubric, optional auto-scorer
python cli.py run my_domain --score --judge gemini
```

## Tips

- **Don't judge yourself.** Don't use a model as its own judge — pick a neutral one.
- **Gemini is a good free judge.** If testing Gemini as a contestant, use DeepSeek or Anthropic as judge.
- **Head-to-head catches bias.** Models prefer outputs shown first. The `--head-to-head` flag runs comparisons twice with reversed order to neutralize this.
- **Check fabricated content.** In domain packs like PF2e, the most revealing metric is whether the model invented things that don't exist.
