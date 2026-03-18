#!/usr/bin/env python3
"""
llm-eval CLI — Multi-LLM Evaluation Framework

Usage:
    python cli.py list-providers
    python cli.py list-packs
    python cli.py run starter --score --judge gemini
    python cli.py score results/<ts>_starter/results.json --judge gemini
    python cli.py new-pack my_domain
"""

import argparse
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def cmd_list_providers(args: argparse.Namespace) -> None:
    from llm_eval.providers import list_available, CLOUD_PROVIDERS, LOCAL_PROVIDERS

    print("\n  Cloud providers:")
    for key, cfg, avail, reason in list_available():
        if key not in CLOUD_PROVIDERS:
            continue
        icon = "+" if avail else "-"
        print(f"    [{icon}] {key:.<25} {cfg.name:<30} [{cfg.tier}] — {reason}")

    print("\n  Local providers (Ollama):")
    for key, cfg, avail, reason in list_available():
        if key not in LOCAL_PROVIDERS:
            continue
        icon = "+" if avail else "-"
        print(f"    [{icon}] {key:.<25} {cfg.name:<30} {cfg.model}")
        if not avail:
            print(f"       └─ {reason}")
    print()


def cmd_list_packs(args: argparse.Namespace) -> None:
    from llm_eval.discovery import discover_packs

    packs = discover_packs()
    if not packs:
        print("No challenge packs found.")
        return

    print(f"\n  {len(packs)} pack(s) found:\n")
    for p in packs:
        prompts = p.get_prompts()
        criteria = p.get_rubric().criteria
        auto = "yes" if p.get_auto_scorer() else "no"
        print(f"    {p.name:.<20} {p.description}")
        print(f"      {len(prompts)} prompts, {len(criteria)} criteria, auto-scorer: {auto}")
    print()


def cmd_run(args: argparse.Namespace) -> None:
    from llm_eval.discovery import get_pack_by_name
    from llm_eval.providers import list_available
    from llm_eval.runner import run_challenges

    pack = get_pack_by_name(args.pack)
    if pack is None:
        print(f"Pack '{args.pack}' not found. Use 'list-packs' to see available packs.")
        sys.exit(1)

    # Determine providers
    if args.providers:
        provider_keys = args.providers
    else:
        provider_keys = [k for k, _, avail, _ in list_available() if avail]

    if not provider_keys:
        print("No providers available! Add API keys to .env or start Ollama.")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    search = getattr(args, 'search', False)
    if search:
        print("Web search ENABLED for providers that support it\n")

    results = run_challenges(
        provider_keys, pack, output_dir, prompt_keys=args.prompt_keys,
        search=search,
    )

    # Optional scoring
    if args.score:
        from llm_eval.judge import score_individual, score_head_to_head
        from llm_eval.report import generate_report

        judge_key = args.judge or "gemini"

        # Warn if judge is also a contestant
        contestants = {r.provider for r in results if not r.error}
        if judge_key in contestants:
            print(f"\nWARNING: Judge '{judge_key}' is also a contestant — results may be biased.\n")

        print("\nScoring results...")
        valid_results = [r for r in results if not r.error]
        scores = score_individual(valid_results, pack, judge_key)

        h2h = None
        if args.head_to_head:
            print("\nRunning head-to-head comparisons...")
            h2h = score_head_to_head(valid_results, pack, judge_key)

        # Log summary
        from llm_eval.log import log_summary
        log_summary(scores, h2h or None)

        # Find the run directory from the results
        run_dirs = list(output_dir.glob(f"*_{pack.name}"))
        report_dir = run_dirs[-1] if run_dirs else output_dir
        generate_report(scores, h2h, pack, judge_key, report_dir)


def cmd_score(args: argparse.Namespace) -> None:
    from llm_eval.discovery import get_pack_by_name
    from llm_eval.judge import score_individual, score_head_to_head
    from llm_eval.report import generate_report
    from llm_eval.runner import load_results

    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"File not found: {results_path}")
        sys.exit(1)

    results = load_results(results_path)
    print(f"Loaded {len(results)} results from {results_path}")

    # Infer pack from results
    pack_name = args.pack
    if not pack_name:
        # Guess from directory name: <timestamp>_<pack_name>
        parent = results_path.parent.name
        parts = parent.rsplit("_", 1)
        if len(parts) > 1:
            pack_name = parts[-1]

    pack = get_pack_by_name(pack_name) if pack_name else None
    if pack is None:
        print(f"Could not determine pack. Use --pack to specify.")
        sys.exit(1)

    judge_key = args.judge or "gemini"
    valid_results = [r for r in results if not r.error]

    print(f"Using judge: {judge_key}")
    print(f"Pack: {pack.name}\n")

    # Init log in the results directory
    from llm_eval.log import init_log, log_summary
    init_log(results_path.parent, pack.name)

    scores = score_individual(valid_results, pack, judge_key)

    h2h = None
    if args.head_to_head:
        print("\nRunning head-to-head comparisons...")
        h2h = score_head_to_head(valid_results, pack, judge_key)

    log_summary(scores, h2h or None)

    output_dir = results_path.parent
    generate_report(scores, h2h, pack, judge_key, output_dir)


def cmd_new_pack(args: argparse.Namespace) -> None:
    packs_dir = Path(__file__).parent / "packs"
    template_dir = packs_dir / "_template"
    target_dir = packs_dir / args.name

    if target_dir.exists():
        print(f"Pack '{args.name}' already exists at {target_dir}")
        sys.exit(1)

    if not template_dir.exists():
        print(f"Template not found at {template_dir}")
        sys.exit(1)

    shutil.copytree(template_dir, target_dir)

    # Update pack.py with the new name
    pack_file = target_dir / "pack.py"
    content = pack_file.read_text()
    content = content.replace("template", args.name)
    content = content.replace("Template", args.name.title())
    pack_file.write_text(content)

    print(f"Created new pack at {target_dir}/")
    print(f"Next steps:")
    print(f"  1. Edit {pack_file} — add prompts and rubric")
    print(f"  2. python cli.py list-packs  — verify it loads")
    print(f"  3. python cli.py run {args.name} --score --judge gemini")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="llm-eval — Multi-LLM Evaluation Framework"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list-providers
    subparsers.add_parser("list-providers", help="Show available LLM providers")

    # list-packs
    subparsers.add_parser("list-packs", help="Show available challenge packs")

    # run
    run_parser = subparsers.add_parser("run", help="Run a challenge pack")
    run_parser.add_argument("pack", help="Name of the challenge pack")
    run_parser.add_argument(
        "--providers", nargs="+", help="Limit to specific providers"
    )
    run_parser.add_argument(
        "--prompt-keys", nargs="+", help="Limit to specific prompts"
    )
    run_parser.add_argument(
        "--score", action="store_true", help="Also run scoring after generation"
    )
    run_parser.add_argument(
        "--judge", type=str, help="Judge model for scoring (default: gemini)"
    )
    run_parser.add_argument(
        "--head-to-head", action="store_true", help="Include pairwise comparisons"
    )
    run_parser.add_argument(
        "--output-dir", type=str, default="results", help="Results directory"
    )
    run_parser.add_argument(
        "--search", action="store_true",
        help="Enable web search for providers that support it (gemini, openai, xai)"
    )

    # score
    score_parser = subparsers.add_parser("score", help="Score existing results")
    score_parser.add_argument("results_file", help="Path to results.json")
    score_parser.add_argument(
        "--judge", type=str, help="Judge model (default: gemini)"
    )
    score_parser.add_argument(
        "--head-to-head", action="store_true", help="Include pairwise comparisons"
    )
    score_parser.add_argument(
        "--pack", type=str, help="Pack name (auto-detected from path if omitted)"
    )

    # new-pack
    new_pack_parser = subparsers.add_parser("new-pack", help="Create a new challenge pack")
    new_pack_parser.add_argument("name", help="Name for the new pack")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "list-providers": cmd_list_providers,
        "list-packs": cmd_list_packs,
        "run": cmd_run,
        "score": cmd_score,
        "new-pack": cmd_new_pack,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
