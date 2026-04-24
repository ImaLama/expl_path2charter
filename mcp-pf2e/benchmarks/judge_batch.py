"""Batch judge pass — score all unjudged builds from a benchmark run.

Usage: python benchmarks/judge_batch.py [--run-id RUN_ID]

Loads each judge model once, processes all builds for that model, then moves
to the next. Minimal model swaps compared to per-build judging.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.evaluator import evaluate_build
from orchestrator.pipeline import _unload_all_models

SUITE_PATH = Path(__file__).parent / "suite.json"
RESULTS_PATH = Path(__file__).parent / "results.jsonl"


def load_results(path: Path) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def save_results(path: Path, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def load_suite(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Batch judge pass for unjudged benchmark builds")
    parser.add_argument("--run-id", help="Judge only this run ID (default: latest)")
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--suite", type=Path, default=SUITE_PATH)
    args = parser.parse_args()

    entries = load_results(args.results)
    suite = load_suite(args.suite)
    cases_by_id = {c["id"]: c for c in suite["cases"]}
    configs_by_id = {c["id"]: c for c in suite.get("run_configs", [])}

    # Find target run
    run_id = args.run_id
    if not run_id:
        run_id = max(e["run_id"] for e in entries)

    # Find unjudged builds (judge skipped or score=0 with "judge skipped" note)
    unjudged = []
    for i, e in enumerate(entries):
        if e["run_id"] != run_id:
            continue
        if e.get("evaluator_notes") == "judge skipped" or (
            e.get("theme_score", 0) == 0
            and e.get("synergy_score", 0) == 0
            and e.get("evaluator_notes", "") == "judge skipped"
        ):
            unjudged.append(i)

    if not unjudged:
        print(f"No unjudged builds found in run {run_id}")
        return

    # Group by judge model to minimize swaps
    by_judge: dict[str, list[int]] = {}
    for idx in unjudged:
        config_id = entries[idx]["config_id"]
        config = configs_by_id.get(config_id, {})
        judge_model = config.get("judge_model", entries[idx].get("judge_model", ""))
        if not judge_model:
            print(f"  WARNING: No judge model for config {config_id}, skipping")
            continue
        by_judge.setdefault(judge_model, []).append(idx)

    total = len(unjudged)
    print(f"Run {run_id}: {total} unjudged builds across {len(by_judge)} judge model(s)")

    done = 0
    for judge_model, indices in by_judge.items():
        print(f"\n{'='*60}")
        print(f"  Judge model: {judge_model} — {len(indices)} builds")
        print(f"{'='*60}")

        _unload_all_models()

        for idx in indices:
            entry = entries[idx]
            case = cases_by_id.get(entry["case_id"], {})

            # Load build JSON from saved build file
            build_json = None
            build_text = ""
            builds_dir = Path(__file__).parent.parent / "builds" / "benchmark" / run_id
            suffix = f"_run{entry['run_num']}" if True else ""
            filename = f"{entry['case_id']}_{entry['config_id']}{suffix}.json"
            build_file = builds_dir / filename
            if build_file.exists():
                with open(build_file) as f:
                    saved = json.load(f)
                build_json = saved.get("build")
                build_text = json.dumps(build_json, indent=2) if build_json else ""

            if not build_json:
                print(f"  {entry['case_id']} run{entry['run_num']}: no build JSON found, skipping")
                continue

            t0 = time.time()
            scores = evaluate_build(
                request=case.get("request", entry.get("case_id", "")),
                expect_themes=case.get("expect_themes", []),
                build_json=build_json,
                build_text=build_text,
                validation={
                    "is_valid": entry["valid"],
                    "errors": [{"message": e} for e in entry.get("errors", [])],
                },
                judge_model=judge_model,
            )
            judge_time = round(time.time() - t0, 2)

            # Update entry
            entries[idx]["theme_score"] = scores["theme_score"]
            entries[idx]["synergy_score"] = scores["synergy_score"]
            entries[idx]["overall_score"] = scores["overall_score"]
            entries[idx]["evaluator_notes"] = scores["evaluator_notes"]
            entries[idx]["judge_time"] = judge_time
            entries[idx]["judge_tokens"] = scores.get("judge_tokens", {})

            done += 1
            print(f"  {entry['case_id']} run{entry['run_num']}: "
                  f"theme={scores['theme_score']}, synergy={scores['synergy_score']}, "
                  f"overall={scores['overall_score']} ({judge_time}s) [{done}/{total}]")

            # Also update the build file
            if build_file.exists():
                with open(build_file) as f:
                    saved = json.load(f)
                saved["scores"] = {
                    "theme": scores["theme_score"],
                    "synergy": scores["synergy_score"],
                    "overall": scores["overall_score"],
                    "notes": scores["evaluator_notes"],
                }
                with open(build_file, "w") as f:
                    json.dump(saved, f, indent=2)

        _unload_all_models()

    # Write updated results
    save_results(args.results, entries)
    print(f"\n{'='*60}")
    print(f"Judged {done}/{total} builds. Results updated in {args.results}")


if __name__ == "__main__":
    main()
