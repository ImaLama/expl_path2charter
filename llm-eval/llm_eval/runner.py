"""
Challenge runner — runs prompts from a pack against providers.

Saves results as JSON (full content) and individual markdown files.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .providers import call_provider, get_all_providers
from .types import ChallengePack, GenerationResult


def run_challenges(
    providers: list[str],
    pack: ChallengePack,
    output_dir: Path,
    prompt_keys: list[str] | None = None,
) -> list[GenerationResult]:
    """Run all prompts from a pack against the given providers.

    Args:
        providers: List of provider keys to test.
        pack: The challenge pack to run.
        output_dir: Base results directory.
        prompt_keys: Specific prompt keys to run (None = all).

    Returns:
        List of GenerationResult objects.
    """
    all_providers = get_all_providers()
    prompts = pack.get_prompts()
    system_prompt = pack.get_system_prompt()

    if prompt_keys:
        prompts = [p for p in prompts if p.key in prompt_keys]
        if not prompts:
            print("No matching prompts found.")
            return []

    # Create output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"{ts}_{pack.name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    results: list[GenerationResult] = []

    print(f"Running {len(prompts)} prompt(s) x {len(providers)} provider(s)\n")

    for prompt in prompts:
        print(f"{'=' * 60}")
        print(f"  Prompt: {prompt.label}")
        print(f"{'=' * 60}")

        for provider_key in providers:
            cfg = all_providers.get(provider_key)
            if cfg is None:
                print(f"  Unknown provider: {provider_key}")
                continue

            print(f"  {cfg.name:.<45} ", end="", flush=True)

            result = call_provider(
                cfg, prompt.content, system_prompt=system_prompt
            )
            # Fill in prompt info
            result.prompt_key = prompt.key
            result.prompt_label = prompt.label

            if result.error:
                print(f"ERROR: {result.error[:60]}")
            else:
                tokens = f"{result.output_tokens} tokens" if result.output_tokens else "? tokens"
                print(f"OK {result.elapsed_s}s, {tokens}")

                # Save individual markdown
                md_path = run_dir / f"{prompt.key}_{provider_key}.md"
                header = (
                    f"# {pack.name} — {cfg.name}\n"
                    f"**Prompt:** {prompt.label}  \n"
                    f"**Model:** {result.model}  \n"
                    f"**Time:** {result.elapsed_s}s  \n"
                    f"**Tokens:** {result.input_tokens or '?'} in / "
                    f"{result.output_tokens or '?'} out\n\n---\n\n"
                )
                md_path.write_text(header + result.content)

            results.append(result)

        print()

    # Save results JSON (full content)
    _save_results_json(results, run_dir / "results.json")

    # Save summary JSON (no content)
    _save_summary_json(results, run_dir / "summary.json")

    print(f"Results saved to {run_dir}/")
    return results


def _save_results_json(results: list[GenerationResult], path: Path) -> None:
    """Save full results including content."""
    data = [_result_to_dict(r) for r in results]
    path.write_text(json.dumps(data, indent=2, default=str))


def _save_summary_json(results: list[GenerationResult], path: Path) -> None:
    """Save results without content field."""
    data = []
    for r in results:
        d = _result_to_dict(r)
        d.pop("content", None)
        data.append(d)
    path.write_text(json.dumps(data, indent=2, default=str))


def _result_to_dict(r: GenerationResult) -> dict:
    """Convert a GenerationResult to a plain dict."""
    return {
        "provider": r.provider,
        "model": r.model,
        "name": r.name,
        "tier": r.tier,
        "prompt_key": r.prompt_key,
        "prompt_label": r.prompt_label,
        "content": r.content,
        "elapsed_s": r.elapsed_s,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "error": r.error,
    }


def load_results(path: Path) -> list[GenerationResult]:
    """Load GenerationResult objects from a results.json file."""
    data = json.loads(path.read_text())
    results = []
    for d in data:
        results.append(GenerationResult(
            provider=d["provider"],
            model=d.get("model", ""),
            name=d.get("name", ""),
            tier=d.get("tier", ""),
            prompt_key=d.get("prompt_key", ""),
            prompt_label=d.get("prompt_label", ""),
            content=d.get("content", ""),
            elapsed_s=d.get("elapsed_s", 0.0),
            input_tokens=d.get("input_tokens"),
            output_tokens=d.get("output_tokens"),
            error=d.get("error"),
        ))
    return results
