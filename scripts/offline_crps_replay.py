#!/usr/bin/env python3
"""
Offline CRPS Replay Script
Runs CRPS calculation on saved predictions and generates diagnostics.
"""

import sys
import os
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from synth.miner.offline_crps.replay import CRPSReplay
from synth.miner.offline_crps.diagnostics import (
    generate_diagnostics_report,
    print_diagnostics_report,
)
from synth.miner.prediction_logger import get_prediction_logger


def main():
    parser = argparse.ArgumentParser(
        description="Offline CRPS replay and diagnostics"
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to replay (default: 30)",
    )
    
    parser.add_argument(
        "--asset",
        type=str,
        default=None,
        help="Filter by asset (optional)",
    )
    
    parser.add_argument(
        "--prompt",
        type=str,
        choices=["low", "high"],
        default=None,
        help="Filter by prompt label (optional)",
    )
    
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD), defaults to --days ago",
    )
    
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD), defaults to today",
    )
    
    parser.add_argument(
        "--diagnostics-only",
        action="store_true",
        help="Only run diagnostics on existing CRPS results (skip replay)",
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for diagnostics report (JSON)",
    )
    
    args = parser.parse_args()
    
    # Parse dates
    end_date = datetime.now(timezone.utc)
    if args.end_date:
        end_date = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
    
    if args.start_date:
        start_date = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
    else:
        start_date = end_date - timedelta(days=args.days)
    
    print("=" * 60)
    print("Offline CRPS Replay")
    print("=" * 60)
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    if args.asset:
        print(f"Asset filter: {args.asset}")
    if args.prompt:
        print(f"Prompt filter: {args.prompt}")
    print()
    
    # Step 1: Replay predictions (unless diagnostics-only)
    crps_results = []
    
    if not args.diagnostics_only:
        print("Step 1: Replaying predictions...")
        replay = CRPSReplay()
        
        crps_results = replay.replay_all_predictions(
            start_date=start_date,
            end_date=end_date,
            asset=args.asset,
            prompt_label=args.prompt,
        )
        
        print(f"✅ Replayed {len(crps_results)} predictions\n")
    else:
        print("Step 1: Loading existing CRPS results...")
        # Load from results directory
        replay = CRPSReplay()
        results_dir = replay.results_dir
        
        crps_results = []
        current_date = start_date.replace(day=1)
        while current_date <= end_date:
            month_dir = results_dir / current_date.strftime("%Y-%m")
            if month_dir.exists():
                for jsonl_file in month_dir.glob("crps_results_*.jsonl"):
                    import json
                    try:
                        with open(jsonl_file, "r") as f:
                            for line in f:
                                result = json.loads(line)
                                result_date = datetime.fromisoformat(result["t0"])
                                if start_date <= result_date <= end_date:
                                    if args.asset and result["asset"] != args.asset:
                                        continue
                                    if args.prompt and result["prompt"] != args.prompt:
                                        continue
                                    crps_results.append(result)
                    except Exception as e:
                        print(f"Warning: Error reading {jsonl_file}: {e}")
            
            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)
        
        print(f"✅ Loaded {len(crps_results)} CRPS results\n")
    
    if not crps_results:
        print("⚠️  No CRPS results found. Run replay first or check date range.")
        return 1
    
    # Step 2: Generate diagnostics
    print("Step 2: Generating diagnostics...")
    report = generate_diagnostics_report(crps_results)
    
    # Print diagnostics
    print_diagnostics_report(report)
    
    # Save to file if requested
    if args.output:
        import json
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n✅ Diagnostics saved to: {args.output}")
    
    print("\n" + "=" * 60)
    print("✅ Offline CRPS replay completed")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
