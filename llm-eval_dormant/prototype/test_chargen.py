#!/usr/bin/env python3
"""
Multi-LLM Pathfinder 2e Character Generator Test Harness

Tests multiple LLM providers (cloud AND local) with the same PF2e character
generation prompt. All cloud providers use the OpenAI-compatible SDK except
Anthropic (own SDK). Local models go through Ollama's OpenAI-compatible API.

Usage:
    cp .env.example .env   # fill in your API keys
    pip install -r requirements.txt
    python test_chargen.py
    python test_chargen.py --prompt custom_prompt.txt
    python test_chargen.py --providers gemini deepseek ollama-qwen32b
    python test_chargen.py --list-providers
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Provider configs
# ---------------------------------------------------------------------------
# Cloud providers — OpenAI-compatible except Anthropic
CLOUD_PROVIDERS = {
    "gemini": {
        "name": "Google Gemini 2.5 Pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_key": "GEMINI_API_KEY",
        "model": "gemini-2.5-pro",
        "tier": "free",
    },
    "deepseek": {
        "name": "DeepSeek V3.2",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
        "tier": "free (5M tokens)",
    },
    "xai": {
        "name": "xAI Grok 4.1",
        "base_url": "https://api.x.ai/v1",
        "env_key": "XAI_API_KEY",
        "model": "grok-4-1",
        "tier": "$25 free credits",
    },
    "openai": {
        "name": "OpenAI GPT-5.2",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "model": "gpt-5.2",
        "tier": "$5 prepaid",
    },
    "anthropic": {
        "name": "Anthropic Claude Opus 4.6",
        "env_key": "ANTHROPIC_API_KEY",
        "model": "claude-opus-4-6",
        "tier": "$5 prepaid",
        "native_sdk": True,
    },
}

# Local providers — all go through Ollama's OpenAI-compatible API
# These require Ollama running locally with the model pulled.
# Ollama URL is configurable via OLLAMA_BASE_URL env var.
LOCAL_PROVIDERS = {
    "ollama-qwen32b": {
        "name": "Qwen 2.5 32B (local)",
        "model": "qwen2.5:32b-instruct-q5_K_M",
        "tier": "local",
    },
    "ollama-qwen72b": {
        "name": "Qwen 2.5 72B (local)",
        "model": "qwen2.5:72b-instruct-q4_K_M",
        "tier": "local",
    },
    "ollama-llama70b": {
        "name": "Llama 3.1 70B (local)",
        "model": "llama3.1:70b-instruct-q4_K_M",
        "tier": "local",
    },
    "ollama-nemo": {
        "name": "Mistral Nemo 12B (local)",
        "model": "mistral-nemo:12b-instruct",
        "tier": "local",
    },
    "ollama-mixtral": {
        "name": "Mixtral 8x7B (local)",
        "model": "mixtral:8x7b-instruct-v0.1-q4_K_M",
        "tier": "local",
    },
    "ollama-deepseek32b": {
        "name": "DeepSeek-R1 32B (local)",
        "model": "deepseek-r1:32b",
        "tier": "local",
    },
}

# Merge into one dict
PROVIDERS = {**CLOUD_PROVIDERS, **LOCAL_PROVIDERS}

# ---------------------------------------------------------------------------
# Test prompts — multiple prompts for more robust comparison
# ---------------------------------------------------------------------------
PROMPTS = {
    "goblin-inventor": {
        "label": "Level 5 Goblin Inventor (complex, mechanical focus)",
        "content": """\
You are an expert Pathfinder 2nd Edition character builder. Generate a complete, \
mechanically valid PF2e character at level 5 using the following constraints:

**Character Concept:** A cunning Goblin Inventor (from Guns & Gears) who builds \
bizarre contraptions and fights with a modified weapon innovation.

**Requirements:**
1. Full ancestry breakdown: heritage, ancestry feats (levels 1, 5)
2. Background with skill training and feat
3. Class features: innovation choice (weapon), initial and level-up class feats (1, 2, 4)
4. Complete ability scores using the standard boost system (4 free boosts at level 1, \
   plus ancestry/background/class, then level 5 boosts)
5. Skill proficiencies and skill feats (levels 1, 2, 4)
6. General feats (levels 3, 5)
7. Equipment loadout appropriate for level 5 (with 160 gp budget)
8. A weapon innovation with the modification choices available at this level
9. A brief personality/backstory paragraph

**Format:** Use clear headers and be precise about the mechanical sources. \
Flag if anything is uncertain or if you're unsure about a specific rule interaction. \
Do NOT invent feats, features, or rules that don't exist in official PF2e content.""",
    },
    "elf-wizard-simple": {
        "label": "Level 3 Elf Wizard (straightforward, common class)",
        "content": """\
You are an expert Pathfinder 2nd Edition character builder. Generate a complete, \
mechanically valid PF2e character:

**Character Concept:** A level 3 Elf Wizard specializing in evocation magic.

**Requirements:**
1. Ancestry: Elf, with heritage and ancestry feat at level 1
2. Background with skill training and feat
3. Class: Wizard with arcane school (Evocation), class feats at levels 1 and 2
4. Complete ability scores (standard boost system)
5. Prepared spell list for the day (cantrips + leveled spells appropriate for level 3)
6. Skill proficiencies, skill feat at level 2, general feat at level 3
7. Equipment loadout (level 3 budget: 25 gp)
8. Brief personality note

Be precise about mechanical sources. Flag any uncertainty.""",
    },
    "vague-concept": {
        "label": "Vague concept (tests creative interpretation)",
        "content": """\
You are an expert Pathfinder 2nd Edition character builder. I want a level 5 character \
that is sneaky, good with poisons, and has some connection to nature. Maybe a bit feral. \
I don't care about specific class or ancestry — surprise me with something that fits \
this vibe while being mechanically strong.

Build the full character sheet with all mechanical details (ability scores, feats, \
skills, equipment for 160 gp). Flag any rule uncertainties.""",
    },
    "multiclass-tank": {
        "label": "Level 8 Champion/Bard multiclass (hard, tests deep rules knowledge)",
        "content": """\
You are an expert Pathfinder 2nd Edition character builder. Generate a complete, \
mechanically valid PF2e character:

**Character Concept:** A level 8 Human Champion (Paladin cause) who has taken the \
Bard multiclass archetype dedication to gain inspire courage and some healing support.

**Requirements:**
1. Full ancestry + heritage + ancestry feats (1, 5)
2. Background
3. Champion class features and class feats, plus Bard Dedication and follow-up archetype feats
4. Complete ability scores through level 8 (including all boost stages)
5. Proficiencies in all relevant areas (weapons, armor, divine spellcasting, occult via archetype)
6. Spell slots and prepared/spontaneous spells from both traditions
7. Complete feat selection: class (1,2,4,6,8), skill (1,2,4,6,8), general (3,7), ancestry (1,5)
8. Equipment loadout for level 8 (355 gp budget)
9. Brief personality

This is a complex build — be very precise about multiclass archetype rules, \
especially the dedication feat requirements and what archetype feats are available \
at each level. Flag any uncertainties.""",
    },
}

DEFAULT_PROMPT_KEY = "goblin-inventor"


# ---------------------------------------------------------------------------
# API call functions
# ---------------------------------------------------------------------------
def get_ollama_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def check_ollama_model(model: str) -> bool:
    """Check if an Ollama model is available locally."""
    try:
        # Use the Ollama-native API (not OpenAI compat) to list models
        import httpx
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/v1").rstrip("/")
        resp = httpx.get(f"{base}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            # Check for exact match or prefix match (ollama uses name:tag format)
            model_base = model.split(":")[0] if ":" in model else model
            return any(model_base in m for m in models)
    except Exception:
        pass
    return False


def call_openai_compatible(provider_key: str, prompt: str) -> dict:
    """Call a provider using the OpenAI-compatible API."""
    cfg = PROVIDERS[provider_key]

    # Local models use Ollama; cloud models use their own base_url
    if provider_key.startswith("ollama-"):
        base_url = get_ollama_url()
        api_key = "ollama"  # Ollama doesn't need a real key
    else:
        base_url = cfg["base_url"]
        api_key = os.getenv(cfg["env_key"], "")

    client = OpenAI(base_url=base_url, api_key=api_key)

    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4096,
    )
    elapsed = time.perf_counter() - t0

    msg = response.choices[0].message.content
    usage = response.usage
    return {
        "provider": provider_key,
        "model": cfg["model"],
        "name": cfg["name"],
        "tier": cfg["tier"],
        "content": msg,
        "elapsed_s": round(elapsed, 2),
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
    }


def call_anthropic(prompt: str) -> dict:
    """Call Anthropic using its native SDK."""
    import anthropic

    cfg = PROVIDERS["anthropic"]
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    t0 = time.perf_counter()
    response = client.messages.create(
        model=cfg["model"],
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    elapsed = time.perf_counter() - t0

    msg = response.content[0].text
    return {
        "provider": "anthropic",
        "model": cfg["model"],
        "name": cfg["name"],
        "tier": cfg["tier"],
        "content": msg,
        "elapsed_s": round(elapsed, 2),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------
def is_provider_available(provider_key: str) -> tuple[bool, str]:
    """Check if a provider is available. Returns (available, reason)."""
    cfg = PROVIDERS[provider_key]

    if provider_key.startswith("ollama-"):
        if check_ollama_model(cfg["model"]):
            return True, "model loaded"
        # Check if Ollama is running at all
        try:
            import httpx
            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/v1").rstrip("/")
            httpx.get(f"{base}/api/tags", timeout=3)
            return False, f"Ollama running but model '{cfg['model']}' not pulled"
        except Exception:
            return False, "Ollama not running"
    else:
        key = os.getenv(cfg.get("env_key", ""), "").strip()
        if key:
            return True, "API key set"
        return False, "no API key"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Test PF2e character gen across LLMs")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=list(PROVIDERS.keys()),
        help="Only test these providers (default: all available)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Path to a custom prompt file (overrides --prompt-key)",
    )
    parser.add_argument(
        "--prompt-key",
        type=str,
        choices=list(PROMPTS.keys()),
        default=None,
        help="Use a built-in prompt by key (default: all prompts)",
    )
    parser.add_argument(
        "--all-prompts",
        action="store_true",
        default=False,
        help="Run all built-in prompts (default if no --prompt or --prompt-key given)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Directory for output files (default: results/)",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="List all providers and their availability, then exit",
    )
    args = parser.parse_args()

    # List providers mode
    if args.list_providers:
        print("\n  Cloud providers:")
        for key, cfg in CLOUD_PROVIDERS.items():
            avail, reason = is_provider_available(key)
            icon = "✅" if avail else "⏭ "
            print(f"    {icon} {key:.<25} {cfg['name']:<30} [{cfg['tier']}] — {reason}")
        print("\n  Local providers (Ollama):")
        for key, cfg in LOCAL_PROVIDERS.items():
            avail, reason = is_provider_available(key)
            icon = "✅" if avail else "⏭ "
            print(f"    {icon} {key:.<25} {cfg['name']:<30} {cfg['model']}")
            if not avail:
                print(f"       └─ {reason}")
        print()
        sys.exit(0)

    # Determine prompts to run
    if args.prompt:
        prompt_sets = {
            "custom": {"label": f"Custom prompt: {args.prompt}", "content": Path(args.prompt).read_text()}
        }
        print(f"Using custom prompt from {args.prompt}")
    elif args.prompt_key:
        prompt_sets = {args.prompt_key: PROMPTS[args.prompt_key]}
        print(f"Using prompt: {PROMPTS[args.prompt_key]['label']}")
    else:
        prompt_sets = PROMPTS
        print(f"Running all {len(PROMPTS)} built-in prompts")

    # Determine which providers to test
    requested = args.providers or list(PROVIDERS.keys())
    available = []
    print("\nChecking providers:")
    for p in requested:
        avail, reason = is_provider_available(p)
        if avail:
            available.append(p)
            print(f"  ✅ {PROVIDERS[p]['name']:.<40} {reason}")
        else:
            print(f"  ⏭  {PROVIDERS[p]['name']:.<40} {reason}")

    if not available:
        print("\nNo providers available! Add API keys to .env or start Ollama.")
        sys.exit(1)

    print(f"\nTesting {len(available)} provider(s) × {len(prompt_sets)} prompt(s)\n")

    # Run tests
    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_results = []

    for prompt_key, prompt_info in prompt_sets.items():
        prompt = prompt_info["content"]
        print(f"{'='*60}")
        print(f"  Prompt: {prompt_info['label']}")
        print(f"{'='*60}")

        prompt_results = []
        for p in available:
            cfg = PROVIDERS[p]
            print(f"  🔄  {cfg['name']:.<40} ", end="", flush=True)
            try:
                if cfg.get("native_sdk"):
                    result = call_anthropic(prompt)
                else:
                    result = call_openai_compatible(p, prompt)
                result["prompt_key"] = prompt_key
                result["prompt_label"] = prompt_info["label"]
                prompt_results.append(result)
                tokens = f"{result['output_tokens']} tokens" if result["output_tokens"] else "? tokens"
                print(f"✅ {result['elapsed_s']}s, {tokens}")
            except Exception as e:
                print(f"❌ {e}")
                prompt_results.append({
                    "provider": p, "model": cfg["model"], "name": cfg["name"],
                    "prompt_key": prompt_key, "error": str(e),
                })

        # Save individual markdown files
        for r in prompt_results:
            if "error" in r:
                continue
            fname = out_dir / f"{ts}_{prompt_key}_{r['provider']}.md"
            header = (
                f"# PF2e Character — {r['name']}\n"
                f"**Prompt:** {prompt_info['label']}  \n"
                f"**Model:** {r['model']}  \n"
                f"**Time:** {r['elapsed_s']}s  \n"
                f"**Tokens:** {r.get('input_tokens', '?')} in / "
                f"{r.get('output_tokens', '?')} out\n\n---\n\n"
            )
            fname.write_text(header + r["content"])

        all_results.extend(prompt_results)
        print()

    # Save master results JSON (content included — needed by score_chargen.py)
    results_path = out_dir / f"{ts}_results.json"
    results_path.write_text(json.dumps(all_results, indent=2, default=str))

    # Save summary JSON (no content, just metadata)
    summary_path = out_dir / f"{ts}_summary.json"
    summary = [{k: v for k, v in r.items() if k != "content"} for r in all_results]
    summary_path.write_text(json.dumps(summary, indent=2))

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Results saved to {out_dir}/")
    print(f"{'='*60}")
    for prompt_key in prompt_sets:
        prompt_label = prompt_sets[prompt_key]["label"]
        print(f"\n  {prompt_label}:")
        for r in all_results:
            if r.get("prompt_key") != prompt_key:
                continue
            if "error" in r:
                print(f"    {r['name']:.<40} ERROR: {r['error'][:50]}")
            else:
                tokens = r.get("output_tokens", "?")
                print(f"    {r['name']:.<40} {r['elapsed_s']:>6}s  {tokens:>5} tokens")

    print(f"\n  Full results: {results_path}")
    print(f"  Summary:      {summary_path}")
    print(f"  Markdown:     {out_dir}/{ts}_*.md")
    print()


if __name__ == "__main__":
    main()
