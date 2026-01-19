#!/usr/bin/env python3
"""
Historical Mining Simulation and CRPS Testing
Simulates being in the past, runs actual mining logic, and calculates CRPS immediately.
Uses the present mining logic, so it automatically stays in sync with code changes.

Test script location: tests/historical_mining_test.py
Test results location: tests/historical_crps_results/
"""

import sys
import os
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from unittest.mock import patch, MagicMock
import numpy as np
import json
import bittensor as bt
import asyncio

# Add parent directory to path to import synth modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from synth.simulation_input import SimulationInput
from synth.protocol import Simulation
from synth.miner.request_handler import handle_request
from synth.miner.offline_crps.crps_calculation import calculate_crps_for_miner
from synth.miner.offline_crps.prompt_config import LOW_FREQUENCY, HIGH_FREQUENCY
from synth.miner.offline_crps.historical_price_fetcher import (
    fetch_realized_prices,
)
from synth.miner.offline_crps.diagnostics import (
    generate_diagnostics_report,
)
from synth.miner.parameter_governance import get_governance, ParameterGovernance
from synth.utils.helpers import round_time_to_minutes


def extract_price_paths_from_response(response_tuple: tuple) -> List[List[float]]:
    """
    Extract price paths from the response tuple format.
    
    Format: (start_time_unix, time_increment, path_1, path_2, ..., path_1000)
    
    Returns:
        List of price paths (each is list of floats)
    """
    if len(response_tuple) < 3:
        return []
    
    # Skip first two elements (start_time_unix, time_increment)
    price_paths = list(response_tuple[2:])
    return price_paths


def generate_requests_for_period(
    start_date: datetime,
    end_date: datetime,
    prompt_config,
) -> List[Dict[str, Any]]:
    """
    Generate simulation requests for a time period based on prompt config.
    
    Returns:
        List of request dicts with asset, start_time, and config
    """
    requests = []
    
    # Equities launch date (same as validator)
    new_equities_launch = datetime(2026, 1, 20, 14, 0, 0, tzinfo=timezone.utc)
    
    # Calculate cycle interval
    cycle_interval = timedelta(minutes=prompt_config.total_cycle_minutes)
    
    # Start from start_date + initial_delay
    current_time = start_date + timedelta(seconds=prompt_config.initial_delay)
    
    while current_time <= end_date:
        # Determine asset list based on equities launch date
        # Before 2026-01-20 14:00 UTC, only use first 4 assets (BTC, ETH, XAU, SOL)
        if current_time <= new_equities_launch:
            asset_list = prompt_config.asset_list[:4]  # Only BTC, ETH, XAU, SOL
        else:
            asset_list = prompt_config.asset_list  # All assets
        
        # In the validator, request_time is when the request is sent,
        # and start_time is rounded to next minute + timeout_extra_seconds
        # So: request_time < start_time
        # Calculate start_time first
        start_time_dt = round_time_to_minutes(current_time, prompt_config.timeout_extra_seconds)
        
        # request_time should be slightly before start_time
        # Use current_time, but ensure it's at least 1 second before start_time
        request_time = min(current_time, start_time_dt - timedelta(seconds=1))
        
        # Generate request for each asset (using filtered asset_list)
        for asset in asset_list:
            # Only generate if start_time + time_length is within end_date
            end_time_dt = start_time_dt + timedelta(seconds=prompt_config.time_length)
            
            if end_time_dt <= end_date:
                requests.append({
                    "asset": asset,
                    "request_time": request_time,
                    "start_time": start_time_dt,
                    "prompt_config": prompt_config,
                })
        
        # Move to next cycle
        current_time += cycle_interval
    
    return requests


async def process_request(
    request: Dict[str, Any],
    simulated_now: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Process a single request: generate predictions using actual mining logic and calculate CRPS.
    
    Uses the actual handle_request function with mocked datetime.now() to simulate past time.
    
    Returns:
        CRPS result dict, or None if failed
    """
    asset = request["asset"]
    request_time = request["request_time"]
    start_time = request["start_time"]
    prompt_config = request["prompt_config"]
    
    # Create simulation input
    simulation_input = SimulationInput(
        asset=asset,
        start_time=start_time.isoformat(),
        time_increment=prompt_config.time_increment,
        time_length=prompt_config.time_length,
        num_simulations=prompt_config.num_simulations,
    )
    
    bt.logging.info(
        f"Processing request: asset={asset}, "
        f"start_time={start_time.isoformat()}, "
        f"prompt={prompt_config.label}, "
        f"simulated_now={simulated_now.isoformat()}"
    )
    
    # Mock datetime.now() to return simulated_now
    # Use freezegun-like approach: patch the module's datetime import
    import datetime as dt_module
    from unittest.mock import Mock
    
    # Create a mock that preserves datetime functionality
    # We'll use a Mock with spec_set to preserve attributes
    mock_datetime = Mock(spec=dt_module.datetime)
    
    # Override now() method
    def mock_now(tz=None):
        return simulated_now if tz else simulated_now.replace(tzinfo=None)
    mock_datetime.now = mock_now
    
    # Preserve fromisoformat and other needed methods
    mock_datetime.fromisoformat = dt_module.datetime.fromisoformat
    mock_datetime.replace = dt_module.datetime.replace
    
    # Make it callable to create datetime instances
    def datetime_constructor(*args, **kwargs):
        return dt_module.datetime(*args, **kwargs)
    mock_datetime.side_effect = datetime_constructor
    mock_datetime.__call__ = datetime_constructor
    
    # Patch datetime in request_handler module using patch.object on the module
    import synth.miner.request_handler as request_handler_module
    original_datetime = request_handler_module.datetime
    
    try:
        # Replace the datetime in the module
        request_handler_module.datetime = mock_datetime
        
        # Also patch get_current_time in helpers
        with patch('synth.utils.helpers.get_current_time', return_value=simulated_now):
            # Create synapse and call actual handle_request
            synapse = Simulation(simulation_input=simulation_input)
            response_tuple, error = await handle_request(synapse)
    finally:
        # Restore original datetime
        request_handler_module.datetime = original_datetime
    
    if error or response_tuple is None:
        bt.logging.warning(f"Failed to generate predictions: {error}")
        return None
    
    # Extract price paths from response tuple
    price_paths = extract_price_paths_from_response(response_tuple)
    
    if not price_paths or len(price_paths) != 1000:
        bt.logging.warning(f"Wrong number of paths: {len(price_paths) if price_paths else 0} != 1000")
        return None
    
    # Convert to numpy array
    simulation_runs = np.array(price_paths, dtype=np.float64)
    
    # Fetch realized prices
    realized_prices = fetch_realized_prices(
        asset=asset,
        start_time=start_time,
        time_length=prompt_config.time_length,
        time_increment=prompt_config.time_increment,
    )
    
    if realized_prices is None:
        bt.logging.warning(f"Cannot fetch realized prices for {asset} at {start_time}")
        return None
    
    # Ensure same length
    expected_length = prompt_config.time_length // prompt_config.time_increment + 1
    if len(realized_prices) != expected_length:
        bt.logging.warning(
            f"Price length mismatch: {len(realized_prices)} != {expected_length}"
        )
        return None
    
    # Calculate CRPS
    try:
        total_crps, detailed_crps_data = calculate_crps_for_miner(
            simulation_runs=simulation_runs,
            real_price_path=realized_prices,
            time_increment=prompt_config.time_increment,
            scoring_intervals=prompt_config.scoring_intervals,
        )
    except Exception as e:
        bt.logging.error(f"CRPS calculation failed: {e}", exc_info=True)
        return None
    
    # Compile results
    result = {
        "t0": start_time.isoformat(),
        "request_time": request_time.isoformat(),
        "asset": asset,
        "prompt": prompt_config.label,
        "total_crps": float(total_crps),
        "detailed_crps": detailed_crps_data,
        "simulated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    return result


def save_result(result: Dict[str, Any], results_dir: Path):
    """Save CRPS result to disk."""
    t0_str = result["t0"]
    t0 = datetime.fromisoformat(t0_str)
    
    # Save to monthly directory
    month_dir = results_dir / t0.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"historical_crps_{t0.strftime('%Y-%m-%d')}.jsonl"
    filepath = month_dir / filename
    
    try:
        with open(filepath, "a") as f:
            json.dump(result, f)
            f.write("\n")
    except Exception as e:
        bt.logging.error(f"Failed to save result: {e}")


def process_parameter_updates(
    results: List[Dict[str, Any]],
    simulated_date: datetime,
    governance: ParameterGovernance,
) -> List[Dict[str, Any]]:
    """
    Process parameter updates based on CRPS results.
    
    Args:
        results: List of CRPS results
        simulated_date: Current simulated date for governance checks
        governance: Parameter governance instance
    
    Returns:
        List of applied parameter changes
    """
    if not results:
        return []
    
    try:
        # Generate diagnostics from results
        diagnostics = generate_diagnostics_report(results)
        
        # Get tuning suggestions
        suggestions = governance.get_tuning_suggestions(diagnostics)
        
        if not suggestions:
            bt.logging.info("No parameter tuning suggestions (performance is good)")
            return []
        
        applied_changes = []
        
        for suggestion in suggestions:
            asset = suggestion.get("asset", "ALL")
            parameter = suggestion.get("parameter")
            direction = suggestion.get("direction")
            change = suggestion.get("change", 0)
            reason = suggestion.get("reason", "")
            
            # For "ALL" assets, apply to each asset
            assets_to_update = ["BTC", "ETH", "XAU", "SOL"] if asset == "ALL" else [asset]
            
            for asset_name in assets_to_update:
                # Get current value
                current_value = governance.get_current_parameter_value(asset_name, parameter)
                if current_value is None:
                    continue
                
                # Calculate new value
                new_value = current_value + change
                
                # Propose change (this checks eligibility and bounds)
                success, message = governance.propose_parameter_change(
                    asset=asset_name,
                    parameter_name=parameter,
                    new_value=new_value,
                    reason=reason,
                )
                
                if success:
                    applied_changes.append({
                        "asset": asset_name,
                        "parameter": parameter,
                        "old_value": current_value,
                        "new_value": new_value,
                        "reason": reason,
                        "date": simulated_date.isoformat(),
                    })
                    bt.logging.info(
                        f"✅ Applied parameter update: {asset_name}/{parameter} "
                        f"{current_value:.4f} -> {new_value:.4f} ({reason})"
                    )
                else:
                    bt.logging.debug(
                        f"⏭️  Skipped parameter update: {asset_name}/{parameter} - {message}"
                    )
        
        return applied_changes
    
    except Exception as e:
        bt.logging.error(f"Error processing parameter updates: {e}", exc_info=True)
        return []


async def main_async():
    parser = argparse.ArgumentParser(
        description="Historical mining simulation and CRPS testing"
    )
    
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD) - simulate being at this date",
    )
    
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD), defaults to start_date + 1 day",
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of days from start_date (alternative to --end-date)",
    )
    
    parser.add_argument(
        "--prompt",
        type=str,
        choices=["low", "high", "both"],
        default="both",
        help="Which prompt types to simulate (default: both)",
    )
    
    parser.add_argument(
        "--asset",
        type=str,
        default=None,
        help="Filter by asset (optional)",
    )
    
    parser.add_argument(
        "--results-dir",
        type=str,
        default=None,
        help="Directory to save results (default: tests/historical_crps_results)",
    )
    
    parser.add_argument(
        "--enable-tuning",
        action="store_true",
        help="Enable parameter tuning based on CRPS results",
    )
    
    parser.add_argument(
        "--tuning-batch-days",
        type=int,
        default=14,
        help="Days between tuning checks (default: 14)",
    )
    
    parser.add_argument(
        "--tuning-state-file",
        type=str,
        default=None,
        help="Path to tuning history file (default: tests/historical_tuning_history.json)",
    )
    
    args = parser.parse_args()
    
    # Parse dates
    try:
        start_date = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: Invalid start-date format: {args.start_date}")
        print("Expected format: YYYY-MM-DD")
        return 1
    
    if args.end_date:
        try:
            end_date = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Error: Invalid end-date format: {args.end_date}")
            print("Expected format: YYYY-MM-DD")
            return 1
    elif args.days:
        end_date = start_date + timedelta(days=args.days)
    else:
        end_date = start_date + timedelta(days=1)
    
    if end_date <= start_date:
        print("Error: end_date must be after start_date")
        return 1
    
    print("=" * 60)
    print("Historical Mining Simulation and CRPS Testing")
    print("=" * 60)
    print(f"Simulating period: {start_date.date()} to {end_date.date()}")
    print(f"Prompt types: {args.prompt}")
    if args.asset:
        print(f"Asset filter: {args.asset}")
    if args.enable_tuning:
        print(f"Parameter tuning: ENABLED (batch interval: {args.tuning_batch_days} days)")
    print()
    
    # Setup results directory - default to tests/historical_crps_results
    if args.results_dir:
        results_dir = Path(args.results_dir)
    else:
        # Default to tests/historical_crps_results relative to project root
        results_dir = project_root / "tests" / "historical_crps_results"
    
    results_dir.mkdir(parents=True, exist_ok=True)
    print(f"Results will be saved to: {results_dir}")
    
    # Setup parameter governance if tuning is enabled
    governance = None
    tuning_state_file = None
    if args.enable_tuning:
        if args.tuning_state_file:
            tuning_state_file = Path(args.tuning_state_file)
        else:
            tuning_state_file = project_root / "tests" / "historical_tuning_history.json"
        
        # Initialize governance with custom state file
        governance = ParameterGovernance(state_file=str(tuning_state_file))
        # Set miner start date to simulation start date
        governance.miner_start_date = start_date.replace(tzinfo=None)
        governance.tuning_history["miner_start_date"] = start_date.isoformat()
        governance._save_history()
        print(f"Tuning state file: {tuning_state_file}")
    
    print()
    
    # Process requests in batches if tuning is enabled, otherwise process all at once
    if args.enable_tuning:
        # Process in batches for parameter tuning
        batch_size_days = args.tuning_batch_days
        current_start = start_date
        all_results = []
        all_parameter_changes = []
        batch_num = 0
        
        while current_start < end_date:
            batch_num += 1
            current_end = min(current_start + timedelta(days=batch_size_days), end_date)
            
            print(f"\n{'='*60}")
            print(f"Batch {batch_num}: {current_start.date()} to {current_end.date()}")
            print(f"{'='*60}")
            
            # Generate requests for this batch
            batch_requests = []
            if args.prompt in ["low", "both"]:
                batch_requests.extend(generate_requests_for_period(
                    current_start, current_end, LOW_FREQUENCY
                ))
            if args.prompt in ["high", "both"]:
                batch_requests.extend(generate_requests_for_period(
                    current_start, current_end, HIGH_FREQUENCY
                ))
            
            if args.asset:
                batch_requests = [r for r in batch_requests if r["asset"] == args.asset]
            
            print(f"Processing {len(batch_requests)} requests in this batch...")
            # Process batch
            batch_results = []
            for i, request in enumerate(batch_requests):
                if (i + 1) % 10 == 0:
                    print(f"  Processed {i+1}/{len(batch_requests)} requests...")
                
                simulated_now = request["request_time"]
                result = await process_request(request, simulated_now)
                
                if result:
                    save_result(result, results_dir)
                    batch_results.append(result)
                    all_results.append(result)
            
            print(f"  ✅ Batch complete: {len(batch_results)}/{len(batch_requests)} successful")
            
            # After batch, check for parameter updates
            if batch_results and governance:
                print(f"\n  Checking for parameter updates...")
                
                # Mock datetime.now() for governance checks
                # Since parameter_governance uses "from datetime import datetime",
                # we need to patch datetime.now in that module
                with patch('synth.miner.parameter_governance.datetime.now', return_value=current_end.replace(tzinfo=None)):
                    parameter_changes = process_parameter_updates(
                        batch_results,
                        simulated_date=current_end,
                        governance=governance,
                    )
                    
                    if parameter_changes:
                        all_parameter_changes.extend(parameter_changes)
                        print(f"  ✅ Applied {len(parameter_changes)} parameter update(s)")
                    else:
                        print(f"  ℹ️  No parameter updates applied")
            
            # Move to next batch
            current_start = current_end
        
        results = all_results
        
        # Print parameter changes summary
        if all_parameter_changes:
            print(f"\n{'='*60}")
            print(f"Parameter Updates Summary")
            print(f"{'='*60}")
            print(f"Total updates applied: {len(all_parameter_changes)}")
            for change in all_parameter_changes:
                print(
                    f"  {change['date'][:10]}: {change['asset']}/{change['parameter']} "
                    f"{change['old_value']:.4f} -> {change['new_value']:.4f}"
                )
    else:
        # Process all requests at once (no tuning)
        all_requests = []
        
        if args.prompt in ["low", "both"]:
            low_requests = generate_requests_for_period(
                start_date, end_date, LOW_FREQUENCY
            )
            all_requests.extend(low_requests)
        
        if args.prompt in ["high", "both"]:
            high_requests = generate_requests_for_period(
                start_date, end_date, HIGH_FREQUENCY
            )
            all_requests.extend(high_requests)
        
        # Filter by asset if specified
        if args.asset:
            all_requests = [r for r in all_requests if r["asset"] == args.asset]
        
        print(f"Generated {len(all_requests)} requests to process")
        
        # Process requests
        results = []
        for i, request in enumerate(all_requests):
            if (i + 1) % 10 == 0:
                print(f"Processed {i+1}/{len(all_requests)} requests...")
            
            # Use request_time as simulated_now (when the request would have been received)
            simulated_now = request["request_time"]
            
            result = await process_request(request, simulated_now)
            
            if result:
                save_result(result, results_dir)
                results.append(result)
    
    print()
    print("=" * 60)
    print(f"✅ Completed: {len(results)} requests processed successfully")
    print(f"Results saved to: {results_dir}")
    if args.enable_tuning and tuning_state_file:
        print(f"Tuning history saved to: {tuning_state_file}")
    print("=" * 60)
    
    # Print summary
    if results:
        total_crps = sum(r["total_crps"] for r in results)
        avg_crps = total_crps / len(results)
        print(f"\nSummary:")
        print(f"  Total requests processed: {len(results)}")
        print(f"  Average CRPS: {avg_crps:.2f}")
        print(f"  Total CRPS: {total_crps:.2f}")
    
    return 0


def main():
    """Entry point that runs async main."""
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
