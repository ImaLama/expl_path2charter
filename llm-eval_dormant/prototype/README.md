# PF2e Character Generation — Multi-LLM Test Harness

Tests the same Pathfinder 2e character generation prompt across multiple LLM providers.

## Quick Start

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Add your API keys
cp .env.example .env
# Edit .env — only fill in the providers you have keys for, the rest are skipped

# 3. Run
python test_chargen.py

# Test specific providers only
python test_chargen.py --providers gemini deepseek

# Use a custom prompt
python test_chargen.py --prompt my_prompt.txt
```

## Providers

| Key        | Model              | Free?                 | Signup URL                   |
|------------|--------------------|-----------------------|------------------------------|
| `gemini`   | Gemini 2.5 Pro     | Yes, 100 req/day      | aistudio.google.com          |
| `deepseek` | DeepSeek V3.2      | 5M tokens, no card    | platform.deepseek.com        |
| `xai`      | Grok 4.1           | $25 free credits      | console.x.ai                 |
| `openai`   | GPT-5.2            | $5 minimum prepaid    | platform.openai.com          |
| `anthropic`| Claude Opus 4.6    | $5 minimum prepaid    | console.anthropic.com        |

## Output

Results go into `results/` as individual markdown files (one per provider) plus a summary JSON with timing and token counts.

## Customising

Edit the `DEFAULT_PROMPT` in `test_chargen.py` or pass `--prompt yourfile.txt`.
Edit `PROVIDERS` dict to change models (e.g. swap `gpt-5.2` for `gpt-5.4`).
