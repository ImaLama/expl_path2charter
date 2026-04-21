"""CLI entry point for PF2e build orchestrator."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.pipeline import run_build, LOCAL_MODELS


def main():
    parser = argparse.ArgumentParser(
        description="Generate validated PF2e character builds using a local LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Open-ended concept — LLM picks class, ancestry, level
  python -m orchestrator.cli --request "a sneaky caster who fights up close"

  # Partially constrained
  python -m orchestrator.cli --class magus --level 5 --request "sneaky close-range caster"

  # Fully specified
  python -m orchestrator.cli --class thaumaturge --level 4 --ancestry goblin --dedications champion
""",
    )

    parser.add_argument("--class", dest="class_name", default="", help="Character class (e.g., thaumaturge, wizard). Optional — LLM chooses if omitted.")
    parser.add_argument("--level", type=int, default=0, help="Character level (1-20). Optional — LLM chooses if omitted.")
    parser.add_argument("--ancestry", default="", help="Character ancestry (e.g., goblin, elf)")
    parser.add_argument("--dedications", nargs="*", default=[], help="Archetype dedications (e.g., champion exemplar)")
    parser.add_argument("--model", default="ollama-qwen3-32b", choices=list(LOCAL_MODELS.keys()), help="Ollama model (default: ollama-qwen3-32b)")
    parser.add_argument("--max-repairs", type=int, default=2, help="Max repair iterations (default: 2)")
    parser.add_argument("--format", dest="output_format", choices=["json", "markdown"], default="json", help="Output format (default: json)")
    parser.add_argument("--output", help="Save result to directory")
    parser.add_argument("--request", default="", help="Optional free-text flavor for the prompt")
    parser.add_argument("--skip-semantic", action="store_true", default=None, help="Skip embedding search in validation (default: auto based on model size)")
    parser.add_argument("--quiet", action="store_true", help="Suppress step-by-step output")

    args = parser.parse_args()

    if not args.class_name and not args.request:
        parser.error("Either --class or --request is required. Use --request for open-ended concepts.")

    result = run_build(
        class_name=args.class_name,
        character_level=args.level,
        ancestry_name=args.ancestry,
        dedications=args.dedications,
        request=args.request,
        provider_key=args.model,
        max_repairs=args.max_repairs,
        output_format=args.output_format,
        skip_semantic=args.skip_semantic,
        verbose=not args.quiet,
    )

    # Print the build
    print("\n" + "=" * 60)
    if result.get("build_json"):
        print(json.dumps(result["build_json"], indent=2))
    else:
        print(result.get("build_text", "(no output)"))
    print("=" * 60)

    # Print validation summary
    v = result["validation"]
    if v["is_valid"]:
        print(f"\nVALID — {len(v['verified_feats'])} feats verified")
    else:
        print(f"\nINVALID — {len(v['errors'])} errors:")
        for e in v["errors"]:
            print(f"  [{e['rule']}] {e['message']}")
    if v["warnings"]:
        print(f"Warnings: {len(v['warnings'])}")
        for w in v["warnings"]:
            print(f"  [{w['rule']}] {w['message']}")

    # Save if requested
    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{args.class_name}_lvl{args.level}"
        if args.ancestry:
            filename = f"{args.ancestry}_{filename}"

        out_path = out_dir / f"{filename}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
