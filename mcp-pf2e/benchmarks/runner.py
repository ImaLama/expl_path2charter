"""Benchmark runner — cases x configs matrix through the pipeline."""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.pipeline import run_build, LOCAL_MODELS, THINKING_MODELS, _unload_all_models
from benchmarks.evaluator import evaluate_build

SUITE_PATH = Path(__file__).parent / "suite.json"
RESULTS_PATH = Path(__file__).parent / "results.jsonl"

SUPPORTED_CONFIG_KEYS = {
    "id", "model", "judge_model", "schema_enforced", "temperature", "max_repairs",
    "use_vector_ranking", "ollama_options", "scratchpad_mode", "generation_mode", "notes",
}


def load_suite(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def flag_unsupported(config: dict) -> list[str]:
    """Return list of config keys not yet supported by the pipeline."""
    flags = []
    for key, value in config.items():
        if key not in SUPPORTED_CONFIG_KEYS and value not in (False, None, "", 0):
            flags.append(f"{key}={value}")
    return flags


def next_run_id(results_path: Path) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    seq = 1
    if results_path.exists():
        with open(results_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    rid = entry.get("run_id", "")
                    if rid.startswith(today):
                        num = int(rid.split("_")[-1])
                        seq = max(seq, num + 1)
                except (json.JSONDecodeError, ValueError):
                    continue
    return f"{today}_{seq:03d}"


def run_case(case: dict, config: dict, unsupported: list[str]) -> dict:
    """Run a single benchmark case with a given config."""
    print(f"\n{'='*60}")
    print(f"  Case: {case['id']} — {case['label']}")
    print(f"  Config: {config['id']} ({config['model']})")
    if unsupported:
        print(f"  ⚠ Unsupported config (ignored): {', '.join(unsupported)}")
    print(f"{'='*60}")

    output_format = "json" if config.get("schema_enforced", True) else "markdown"

    result = run_build(
        request=case["request"],
        class_name=case.get("class") or "",
        character_level=case.get("level") or 0,
        ancestry_name=case.get("ancestry") or "",
        dedications=case.get("dedications") or [],
        background_name=case.get("background") or "",
        provider_key=config["model"],
        max_repairs=config.get("max_repairs", 2),
        temperature=config.get("temperature", 0.7),
        output_format=output_format,
        use_vector_ranking=config.get("use_vector_ranking", False),
        ollama_options=config.get("ollama_options"),
        scratchpad_mode=config.get("scratchpad_mode", "none"),
        generation_mode=config.get("generation_mode", "planned"),
        verbose=True,
    )

    if "error" in result:
        print(f"  PIPELINE ERROR: {result['error']}")
        return {
            "valid": False,
            "attempts": 0,
            "timings": result.get("timings", {}),
            "tokens": result.get("tokens", {}),
            "theme_score": 0,
            "synergy_score": 0,
            "overall_score": 0,
            "evaluator_notes": f"Pipeline error: {result['error']}",
            "judge_time": 0,
            "judge_tokens": {},
            "errors": [],
            "warnings": [],
            "skeleton": result.get("skeleton"),
            "build_json": None,
        }

    print(f"\n[benchmark] Unloading generator, loading judge...")
    _unload_all_models()

    scores = evaluate_build(
        request=case["request"],
        expect_themes=case.get("expect_themes", []),
        build_json=result.get("build_json"),
        build_text=result.get("build_text", ""),
        validation=result.get("validation", {}),
        judge_model=config["judge_model"],
    )

    validation = result.get("validation", {})
    return {
        "valid": validation.get("is_valid", False),
        "attempts": result.get("attempts", 1),
        "timings": result.get("timings", {}),
        "tokens": result.get("tokens", {}),
        "theme_score": scores["theme_score"],
        "synergy_score": scores["synergy_score"],
        "overall_score": scores["overall_score"],
        "evaluator_notes": scores["evaluator_notes"],
        "judge_time": scores.get("judge_time", 0),
        "judge_tokens": scores.get("judge_tokens", {}),
        "errors": [e["message"] for e in validation.get("errors", [])],
        "warnings": [w["message"] for w in validation.get("warnings", [])],
        "skeleton": result.get("skeleton"),
        "build_json": result.get("build_json"),
        "slot_stats": result.get("slot_stats"),
        "trace": result.get("trace"),
    }


def run_benchmark(
    suite_path: Path,
    results_path: Path,
    config_filter: list[str] | None = None,
    case_filter: list[str] | None = None,
    runs_per_case: int = 1,
):
    """Run the full cases x configs matrix."""
    suite = load_suite(suite_path)
    cases = suite["cases"]
    configs = suite.get("run_configs", [])

    if case_filter:
        cases = [c for c in cases if c["id"] in case_filter]
    if config_filter:
        configs = [c for c in configs if c["id"] in config_filter]

    if not cases:
        print("No cases matched filter.")
        return
    if not configs:
        print("No configs matched filter.")
        return

    run_id = next_run_id(results_path)

    print(f"Benchmark run: {run_id}")
    print(f"Suite: {suite_path.name} v{suite.get('version', '?')}")
    print(f"Matrix: {len(cases)} cases × {len(configs)} configs × {runs_per_case} runs = {len(cases) * len(configs) * runs_per_case} total")
    print(f"Results: {results_path}")
    print()

    for config in configs:
        unsupported = flag_unsupported(config)
        model_is_thinking = config["model"] in THINKING_MODELS

        print(f"\n{'#'*60}")
        print(f"  Config: {config['id']}")
        print(f"  Model: {config['model']} (thinking={model_is_thinking})")
        print(f"  Judge: {config['judge_model']}")
        if unsupported:
            print(f"  ⚠ Unsupported parameters (will be ignored): {', '.join(unsupported)}")
        if config.get("notes"):
            print(f"  Notes: {config['notes']}")
        print(f"{'#'*60}")

        for case in cases:
            for run_num in range(runs_per_case):
                t0 = time.time()
                case_result = run_case(case, config, unsupported)
                wall_time = round(time.time() - t0, 2)

                entry = {
                    "run_id": run_id,
                    "config_id": config["id"],
                    "case_id": case["id"],
                    "run_num": run_num + 1,
                    "timestamp": datetime.now().isoformat(),
                    "model": config["model"],
                    "model_is_thinking": model_is_thinking,
                    "judge_model": config["judge_model"],
                    "schema_enforced": config.get("schema_enforced", True),
                    "temperature": config.get("temperature", 0.7),
                    "max_repairs": config.get("max_repairs", 2),
                    "ollama_options": config.get("ollama_options"),
                    "suite_version": suite.get("version", "?"),
                    "difficulty": case.get("difficulty", "?"),
                    "wall_time": wall_time,
                    "valid": case_result["valid"],
                    "attempts": case_result["attempts"],
                    "timings": case_result["timings"],
                    "tokens": case_result["tokens"],
                    "theme_score": case_result["theme_score"],
                    "synergy_score": case_result["synergy_score"],
                    "overall_score": case_result["overall_score"],
                    "evaluator_notes": case_result["evaluator_notes"],
                    "judge_time": case_result.get("judge_time", 0),
                    "judge_tokens": case_result.get("judge_tokens", {}),
                    "errors": case_result["errors"],
                    "warnings": case_result["warnings"],
                    "unsupported_config": unsupported,
                    "generation_mode": config.get("generation_mode", "planned"),
                    "slot_stats": case_result.get("slot_stats"),
                    "human_feedback": "",
                }

                with open(results_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")

                # Save build JSON with scores to builds/benchmark/<run_id>/
                if case_result.get("build_json"):
                    builds_dir = Path(__file__).parent.parent / "builds" / "benchmark" / run_id
                    builds_dir.mkdir(parents=True, exist_ok=True)
                    build_file = {
                        "case_id": case["id"],
                        "config_id": config["id"],
                        "run_num": run_num + 1,
                        "model": config["model"],
                        "build": case_result["build_json"],
                        "validation": {
                            "valid": case_result["valid"],
                            "errors": case_result["errors"],
                            "warnings": case_result["warnings"],
                        },
                        "scores": {
                            "theme": case_result["theme_score"],
                            "synergy": case_result["synergy_score"],
                            "overall": case_result["overall_score"],
                            "notes": case_result["evaluator_notes"],
                        },
                        "slot_stats": case_result.get("slot_stats"),
                        "trace": case_result.get("trace"),
                    }
                    suffix = f"_run{run_num + 1}" if runs_per_case > 1 else ""
                    filename = f"{case['id']}_{config['id']}{suffix}.json"
                    with open(builds_dir / filename, "w") as bf:
                        json.dump(build_file, bf, indent=2)

                status = "VALID" if case_result["valid"] else "INVALID"
                print(f"\n  >> {status} | Theme: {case_result['theme_score']} | "
                      f"Synergy: {case_result['synergy_score']} | "
                      f"Overall: {case_result['overall_score']}")

                _unload_all_models()

    print(f"\n{'='*60}")
    print(f"Benchmark {run_id} complete. {len(cases) * len(configs) * runs_per_case} results → {results_path}")


def main():
    parser = argparse.ArgumentParser(description="Run PF2e pipeline benchmarks (cases × configs)")
    parser.add_argument("--suite", type=Path, default=SUITE_PATH,
                        help=f"Suite JSON path (default: {SUITE_PATH})")
    parser.add_argument("--results", type=Path, default=RESULTS_PATH,
                        help=f"Results JSONL path (default: {RESULTS_PATH})")
    parser.add_argument("--configs", nargs="*",
                        help="Filter to specific config IDs")
    parser.add_argument("--cases", nargs="*",
                        help="Filter to specific case IDs")
    parser.add_argument("--runs-per-case", type=int, default=1,
                        help="Runs per case for variance (default: 1)")
    args = parser.parse_args()

    run_benchmark(
        suite_path=args.suite,
        results_path=args.results,
        config_filter=args.configs,
        case_filter=args.cases,
        runs_per_case=args.runs_per_case,
    )


if __name__ == "__main__":
    main()
