"""Benchmark report — reads JSONL results, prints tables and comparisons."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / "results.jsonl"


def load_results(path: Path) -> list[dict]:
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def _aggregate(entries: list[dict]) -> dict:
    """Aggregate multiple runs into pass rate and mean scores."""
    n = len(entries)
    valid = sum(1 for e in entries if e.get("valid"))
    return {
        "n": n,
        "valid": valid,
        "pass_rate": f"{valid}/{n}",
        "mean_attempts": sum(e.get("attempts", 0) for e in entries) / n,
        "mean_time": sum(e.get("wall_time", 0) for e in entries) / n,
        "mean_theme": sum(e.get("theme_score", 0) for e in entries) / n,
        "mean_synergy": sum(e.get("synergy_score", 0) for e in entries) / n,
        "mean_overall": sum(e.get("overall_score", 0) for e in entries) / n,
        "mean_tokens": sum(e.get("tokens", {}).get("total_tokens", 0) for e in entries) / n,
        "scores": [e.get("overall_score", 0) for e in entries],
    }


def cmd_list(results: list[dict]):
    """List all benchmark runs."""
    runs = defaultdict(list)
    for r in results:
        runs[r["run_id"]].append(r)

    print(f"{'Run ID':<20} {'Configs':<35} {'N':>4} {'Valid':>6} {'Avg':>6}")
    print("-" * 75)
    for run_id in sorted(runs):
        entries = runs[run_id]
        configs = sorted(set(e.get("config_id", "?") for e in entries))
        valid = sum(1 for e in entries if e.get("valid"))
        avg = sum(e.get("overall_score", 0) for e in entries) / max(len(entries), 1)
        print(f"{run_id:<20} {', '.join(configs):<35} {len(entries):>4} {valid}/{len(entries):>4} {avg:>6.1f}")


def cmd_show(results: list[dict], run_id: str, config_id: str | None = None):
    """Show detailed results for a run, aggregating multi-run data."""
    entries = [r for r in results if r["run_id"] == run_id]
    if config_id:
        entries = [r for r in entries if r.get("config_id") == config_id]
    if not entries:
        print(f"No results for run_id={run_id}" + (f", config={config_id}" if config_id else ""))
        return

    by_config = defaultdict(list)
    for e in entries:
        by_config[e.get("config_id", "?")].append(e)

    for cid in sorted(by_config):
        c_entries = by_config[cid]
        first = c_entries[0]
        thinking = "yes" if first.get("model_is_thinking") else "no"
        print(f"\nConfig: {cid} | Model: {first['model']} (thinking={thinking}) | Judge: {first.get('judge_model', '?')}")

        unsupported = first.get("unsupported_config", [])
        if unsupported:
            print(f"  Unsupported config params (ignored): {', '.join(unsupported)}")

        # Group by case for multi-run aggregation
        by_case = defaultdict(list)
        for e in c_entries:
            by_case[e["case_id"]].append(e)

        multi_run = any(len(v) > 1 for v in by_case.values())

        if multi_run:
            header = f"  {'Case':<25} {'Pass':>4} {'Att':>4} {'Time':>6} {'Thm':>5} {'Syn':>5} {'Score':>6} {'Scores':>15}"
            print(header)
            print("  " + "-" * (len(header) - 2))

            totals = {"valid": 0, "n": 0, "time": 0, "theme": 0, "synergy": 0, "overall": 0}
            for case_id in sorted(by_case):
                agg = _aggregate(by_case[case_id])
                scores_str = ", ".join(f"{s:.0f}" for s in agg["scores"])
                print(f"  {case_id:<25} {agg['pass_rate']:>4} {agg['mean_attempts']:>4.1f} "
                      f"{agg['mean_time']:>5.0f}s {agg['mean_theme']:>5.1f} {agg['mean_synergy']:>5.1f} "
                      f"{agg['mean_overall']:>6.1f} [{scores_str:>13}]")
                totals["valid"] += agg["valid"]
                totals["n"] += agg["n"]
                totals["time"] += agg["mean_time"]
                totals["theme"] += agg["mean_theme"]
                totals["synergy"] += agg["mean_synergy"]
                totals["overall"] += agg["mean_overall"]

            nc = len(by_case)
            print("  " + "-" * (len(header) - 2))
            print(f"  {'TOTAL':<25} {totals['valid']}/{totals['n']:>2} {'':<4} "
                  f"{totals['time']/nc:>5.0f}s {totals['theme']/nc:>5.1f} {totals['synergy']/nc:>5.1f} "
                  f"{totals['overall']/nc:>6.1f}")
        else:
            header = f"  {'Case':<25} {'Ok':>2} {'Att':>3} {'Time':>6} {'Thm':>4} {'Syn':>4} {'Scr':>5} {'Tok':>7}"
            print(header)
            print("  " + "-" * (len(header) - 2))

            totals = {"time": 0, "tokens": 0, "theme": 0, "synergy": 0, "overall": 0, "valid": 0}
            for e in c_entries:
                v = "Y" if e.get("valid") else "N"
                att = e.get("attempts", 0)
                wall = e.get("wall_time", 0)
                thm = e.get("theme_score", 0)
                syn = e.get("synergy_score", 0)
                scr = e.get("overall_score", 0)
                tok = e.get("tokens", {}).get("total_tokens", 0)
                print(f"  {e['case_id']:<25} {v:>2} {att:>3} {wall:>5.0f}s {thm:>4} {syn:>4} {scr:>5.1f} {tok:>7}")
                totals["time"] += wall
                totals["tokens"] += tok
                totals["theme"] += thm
                totals["synergy"] += syn
                totals["overall"] += scr
                if e.get("valid"):
                    totals["valid"] += 1

            n = len(c_entries)
            print("  " + "-" * (len(header) - 2))
            print(f"  {'Avg':<25} {totals['valid']}/{n:>1} {'':>3} {totals['time']/n:>5.0f}s "
                  f"{totals['theme']/n:>4.1f} {totals['synergy']/n:>4.1f} {totals['overall']/n:>5.1f} {totals['tokens']/n:>7.0f}")

        print(f"\n  Notes:")
        for e in c_entries:
            notes = e.get("evaluator_notes", "")
            if notes:
                suffix = f" (run {e.get('run_num', 1)})" if multi_run else ""
                print(f"    {e['case_id']}{suffix}: {notes}")


def cmd_compare(results: list[dict], run_id: str, config_ids: list[str] | None = None):
    """Compare configs within a run, aggregating multi-run data."""
    entries = [r for r in results if r["run_id"] == run_id]
    if not entries:
        print(f"No results for run_id={run_id}")
        return

    # Group by config → case → list of entries
    by_config: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for e in entries:
        cid = e.get("config_id", "?")
        if config_ids and cid not in config_ids:
            continue
        by_config[cid][e["case_id"]].append(e)

    if len(by_config) < 2:
        print("Need at least 2 configs to compare.")
        return

    config_list = sorted(by_config.keys())
    all_cases = sorted(set(cid for by_case in by_config.values() for cid in by_case))

    col_w = max(12, max(len(c) for c in config_list) + 2)

    # Header
    header = f"{'Case':<25}"
    for c in config_list:
        header += f" {c:>{col_w}}"
    print(header)
    print("-" * len(header))

    # Pass rate row per case
    config_totals: dict[str, dict] = {c: {"valid": 0, "n": 0, "overall": 0, "time": 0, "tokens": 0} for c in config_list}

    for case_id in all_cases:
        line = f"{case_id:<25}"
        for c in config_list:
            case_entries = by_config[c].get(case_id, [])
            if case_entries:
                agg = _aggregate(case_entries)
                cell = f"{agg['pass_rate']} {agg['mean_overall']:.1f}"
                config_totals[c]["valid"] += agg["valid"]
                config_totals[c]["n"] += agg["n"]
                config_totals[c]["overall"] += agg["mean_overall"]
                config_totals[c]["time"] += agg["mean_time"]
                config_totals[c]["tokens"] += agg["mean_tokens"]
            else:
                cell = "-"
            line += f" {cell:>{col_w}}"
        print(line)

    # Summary rows
    print("-" * len(header))
    for label, key, fmt in [
        ("Pass rate", "pass", ""),
        ("Avg score", "score", ""),
        ("Avg time", "time", ""),
        ("Avg tokens", "tokens", ""),
    ]:
        line = f"{label:<25}"
        for c in config_list:
            t = config_totals[c]
            nc = len([cid for cid in all_cases if by_config[c].get(cid)])
            if nc == 0:
                line += f" {'-':>{col_w}}"
                continue
            if key == "pass":
                cell = f"{t['valid']}/{t['n']}"
            elif key == "score":
                cell = f"{t['overall']/nc:.1f}"
            elif key == "time":
                cell = f"{t['time']/nc:.0f}s"
            elif key == "tokens":
                cell = f"{t['tokens']/nc:.0f}"
            line += f" {cell:>{col_w}}"
        print(line)


def main():
    parser = argparse.ArgumentParser(description="View benchmark results")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all runs")

    show_p = sub.add_parser("show", help="Show run details")
    show_p.add_argument("run_id")
    show_p.add_argument("--config", help="Filter to one config")

    cmp_p = sub.add_parser("compare", help="Compare configs within a run")
    cmp_p.add_argument("run_id")
    cmp_p.add_argument("--configs", nargs="*", help="Config IDs to compare (default: all)")

    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return
    if not args.results.exists():
        print(f"No results at {args.results}")
        return

    results = load_results(args.results)

    if args.command == "list":
        cmd_list(results)
    elif args.command == "show":
        cmd_show(results, args.run_id, getattr(args, "config", None))
    elif args.command == "compare":
        cmd_compare(results, args.run_id, getattr(args, "configs", None))


if __name__ == "__main__":
    main()
