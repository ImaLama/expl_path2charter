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


def cmd_list(results: list[dict]):
    """List all benchmark runs."""
    runs = defaultdict(list)
    for r in results:
        runs[r["run_id"]].append(r)

    print(f"{'Run ID':<20} {'Configs':<30} {'Cases':>5} {'Avg':>6}")
    print("-" * 65)
    for run_id in sorted(runs):
        entries = runs[run_id]
        configs = sorted(set(e.get("config_id", "?") for e in entries))
        avg = sum(e.get("overall_score", 0) for e in entries) / max(len(entries), 1)
        print(f"{run_id:<20} {', '.join(configs):<30} {len(entries):>5} {avg:>6.1f}")


def cmd_show(results: list[dict], run_id: str, config_id: str | None = None):
    """Show detailed results for a run, optionally filtered by config."""
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
            print(f"⚠ Unsupported config params (ignored): {', '.join(unsupported)}")

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
                print(f"    {e['case_id']}: {notes}")


def cmd_compare(results: list[dict], run_id: str, config_ids: list[str] | None = None):
    """Compare configs within a run (or across runs)."""
    entries = [r for r in results if r["run_id"] == run_id]
    if not entries:
        print(f"No results for run_id={run_id}")
        return

    by_config = defaultdict(dict)
    for e in entries:
        cid = e.get("config_id", "?")
        if config_ids and cid not in config_ids:
            continue
        by_config[cid][e["case_id"]] = e

    if len(by_config) < 2:
        print("Need at least 2 configs to compare.")
        return

    config_list = sorted(by_config.keys())
    all_cases = sorted(set(cid for by_case in by_config.values() for cid in by_case))

    col_w = 12
    header = f"{'Case':<25}"
    for c in config_list:
        header += f" {c:>{col_w}}"
    print(header)
    print("-" * len(header))

    for case_id in all_cases:
        line = f"{case_id:<25}"
        for c in config_list:
            entry = by_config[c].get(case_id)
            if entry:
                score = entry.get("overall_score", 0)
                line += f" {score:>{col_w}.1f}"
            else:
                line += f" {'—':>{col_w}}"
        print(line)

    print("-" * len(header))
    avg_line = f"{'Average':<25}"
    time_line = f"{'Avg time':<25}"
    token_line = f"{'Avg tokens':<25}"
    for c in config_list:
        vals = list(by_config[c].values())
        avg = sum(e.get("overall_score", 0) for e in vals) / max(len(vals), 1)
        avg_t = sum(e.get("wall_time", 0) for e in vals) / max(len(vals), 1)
        avg_tok = sum(e.get("tokens", {}).get("total_tokens", 0) for e in vals) / max(len(vals), 1)
        avg_line += f" {avg:>{col_w}.1f}"
        time_line += f" {avg_t:>{col_w}.0f}s"
        token_line += f" {avg_tok:>{col_w}.0f}"
    print(avg_line)
    print(time_line)
    print(token_line)


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
