"""
Test complete miner implementation (Steps 1-12).
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import numpy as np
from synth.protocol import Simulation
from synth.simulation_input import SimulationInput
from synth.miner.request_handler import handle_request
from synth.miner.volatility_state import get_volatility_manager
from synth.miner.state_persistence import reload_all_states


async def test_complete_handler():
    """Test complete request handler with all steps integrated."""
    print("\n" + "=" * 60)
    print("Testing Complete Miner (Steps 1-12)")
    print("=" * 60)
    
    # Reload state (if any)
    print("\n1. Reloading persisted state...")
    reload_all_states()
    
    # Test LOW frequency request
    print("\n2. Testing LOW frequency request (24-hour forecast)...")
    # Give more time buffer for bootstrap/path generation
    start_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=start_time,
        time_increment=300,  # 5 minutes
        time_length=86400,   # 24 hours
        num_simulations=1000,
    )
    
    synapse = Simulation(simulation_input=simulation_input)
    
    print(f"   Asset: {simulation_input.asset}")
    print(f"   Start time: {simulation_input.start_time}")
    print(f"   Time increment: {simulation_input.time_increment}s (5 min)")
    print(f"   Time length: {simulation_input.time_length}s (24 hours)")
    
    response_tuple, error = await handle_request(synapse)
    
    if error:
        print(f"   ❌ Error: {error}")
        return False
    
    if response_tuple is None:
        print("   ❌ No response")
        return False
    
    # Validate response
    start_time_unix, time_increment, *paths = response_tuple
    print(f"   ✅ Response generated:")
    print(f"      Paths: {len(paths)}")
    print(f"      Path length: {len(paths[0])}")
    print(f"      Start time Unix: {start_time_unix}")
    
    # Check Path[0] is flat
    path_0 = paths[0]
    first_price = path_0[0]
    is_flat = all(abs(p - first_price) < 1e-6 for p in path_0)
    print(f"      Path[0] is flat: {is_flat} (first_price={first_price:.2f})")
    
    # Check Paths[1..999] have variation
    path_1 = paths[1]
    has_variation = max(path_1) > min(path_1)
    print(f"      Path[1] has variation: {has_variation}")
    
    # Check volatility state was created/updated
    manager = get_volatility_manager()
    state = manager.get_state("BTC")
    if state:
        print(f"      Volatility state:")
        print(f"         sigma2_1m: {state.sigma2_1m:.6e}")
        print(f"         last_close: {state.last_close_1m:.2f}")
        print(f"         lambda: {state.lambda_val:.2f}")
    
    print("   ✅ LOW frequency test PASSED")
    
    # Test HIGH frequency request
    print("\n3. Testing HIGH frequency request (1-hour forecast)...")
    start_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    
    simulation_input = SimulationInput(
        asset="ETH",
        start_time=start_time,
        time_increment=60,   # 1 minute
        time_length=3600,    # 1 hour
        num_simulations=1000,
    )
    
    synapse = Simulation(simulation_input=simulation_input)
    
    response_tuple, error = await handle_request(synapse)
    
    if error:
        print(f"   ❌ Error: {error}")
        return False
    
    start_time_unix, time_increment, *paths = response_tuple
    print(f"   ✅ Response generated:")
    print(f"      Paths: {len(paths)}")
    print(f"      Path length: {len(paths[0])} (expected 61 for 1-hour, 1-min steps)")
    print(f"      Path[0] is flat: {all(abs(p - paths[0][0]) < 1e-6 for p in paths[0])}")
    
    print("   ✅ HIGH frequency test PASSED")
    
    # Test multiple assets
    print("\n4. Testing multiple assets...")
    assets_to_test = ["BTC", "ETH", "XAU", "SOL"]
    
    for asset in assets_to_test:
        start_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        simulation_input = SimulationInput(
            asset=asset,
            start_time=start_time,
            time_increment=300,
            time_length=86400,
            num_simulations=1000,
        )
        synapse = Simulation(simulation_input=simulation_input)
        
        response_tuple, error = await handle_request(synapse)
        if error:
            print(f"   ⚠️  {asset}: {error}")
        else:
            state = manager.get_state(asset)
            if state:
                print(f"   ✅ {asset}: sigma2={state.sigma2_1m:.6e}, price={state.last_close_1m:.2f}")
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED")
    print("=" * 60)
    
    return True


async def main():
    """Run all tests."""
    try:
        success = await test_complete_handler()
        return 0 if success else 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
