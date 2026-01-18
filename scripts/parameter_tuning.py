#!/usr/bin/env python3
"""
Parameter Tuning Helper Script
Check tuning eligibility and propose parameter changes.
"""

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path BEFORE importing bittensor
parent_dir = str(Path(__file__).parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import after path setup (avoid bittensor CLI argument conflicts)
from synth.miner.parameter_governance import get_governance


def main():
    parser = argparse.ArgumentParser(
        description="Parameter tuning governance helper"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Check eligibility
    check_parser = subparsers.add_parser(
        "check",
        help="Check if tuning is eligible",
    )
    check_parser.add_argument("asset", help="Asset symbol")
    check_parser.add_argument(
        "parameter",
        choices=["lambda", "df", "sigma_cap_daily"],
        help="Parameter name",
    )
    
    # Propose change
    propose_parser = subparsers.add_parser(
        "propose",
        help="Propose a parameter change",
    )
    propose_parser.add_argument("asset", help="Asset symbol")
    propose_parser.add_argument(
        "parameter",
        choices=["lambda", "df", "sigma_cap_daily"],
        help="Parameter name",
    )
    propose_parser.add_argument("value", type=float, help="New parameter value")
    propose_parser.add_argument(
        "--reason",
        type=str,
        default="Manual tuning",
        help="Reason for change",
    )
    
    # Get suggestions
    suggest_parser = subparsers.add_parser(
        "suggest",
        help="Get tuning suggestions from diagnostics",
    )
    suggest_parser.add_argument(
        "--diagnostics-file",
        type=str,
        help="Path to diagnostics JSON file",
    )
    
    # Current values
    current_parser = subparsers.add_parser(
        "current",
        help="Show current parameter values",
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    governance = get_governance()
    
    if args.command == "check":
        eligible, reason = governance.is_tuning_eligible(args.asset, args.parameter)
        current_value = governance.get_current_parameter_value(args.asset, args.parameter)
        
        print(f"\nParameter: {args.asset} / {args.parameter}")
        print(f"Current value: {current_value}")
        print(f"Eligible: {'✅ Yes' if eligible else '❌ No'}")
        print(f"Reason: {reason}\n")
        
        if eligible:
            min_val, max_val = governance.get_parameter_bounds(args.asset, args.parameter)
            max_step = governance.get_max_step_size(args.parameter)
            print(f"Bounds: [{min_val}, {max_val}]")
            print(f"Max step size: ±{max_step}")
        
        return 0 if eligible else 1
    
    elif args.command == "propose":
        eligible, reason = governance.is_tuning_eligible(args.asset, args.parameter)
        
        if not eligible:
            print(f"❌ Tuning not eligible: {reason}")
            return 1
        
        current_value = governance.get_current_parameter_value(args.asset, args.parameter)
        
        print(f"\nProposing change:")
        print(f"  Asset: {args.asset}")
        print(f"  Parameter: {args.parameter}")
        print(f"  Current: {current_value}")
        print(f"  New: {args.value}")
        print(f"  Change: {args.value - current_value:+.4f}")
        print(f"  Reason: {args.reason}\n")
        
        success, msg = governance.propose_parameter_change(
            asset=args.asset,
            parameter_name=args.parameter,
            new_value=args.value,
            reason=args.reason,
        )
        
        if success:
            print(f"✅ {msg}\n")
            print("Note: Parameter change is recorded but not yet applied.")
            print("Apply changes by updating config and restarting miner.")
            return 0
        else:
            print(f"❌ {msg}\n")
            return 1
    
    elif args.command == "suggest":
        print("Tuning suggestions (from diagnostics):")
        print("(Run offline_crps_replay.py first to generate diagnostics)")
        
        if args.diagnostics_file:
            import json
            try:
                with open(args.diagnostics_file, "r") as f:
                    diagnostics = json.load(f)
                
                from synth.miner.parameter_governance import ParameterGovernance
                gov = ParameterGovernance()
                suggestions = gov.get_tuning_suggestions(diagnostics)
                
                if suggestions:
                    print("\nSuggestions:")
                    for sug in suggestions:
                        print(f"  {sug}")
                else:
                    print("\n  No suggestions at this time.")
            except Exception as e:
                print(f"Error loading diagnostics: {e}")
                return 1
        else:
            print("\nUse --diagnostics-file to load diagnostics and get suggestions.")
        
        return 0
    
    elif args.command == "current":
        print("\nCurrent Parameter Values:")
        print("=" * 60)
        
        assets = ["BTC", "ETH", "SOL", "XAU"]
        parameters = ["lambda", "df", "sigma_cap_daily"]
        
        for asset in assets:
            print(f"\n{asset}:")
            for param in parameters:
                value = governance.get_current_parameter_value(asset, param)
                eligible, _ = governance.is_tuning_eligible(asset, param)
                status = "✅" if eligible else "⏳"
                print(f"  {param:20s}: {value:8.4f} {status}")
        
        print()
        return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
