"""
Quick test of miner components.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from synth.protocol import Simulation
from synth.simulation_input import SimulationInput
from synth.miner.request_handler import handle_request


async def quick_test():
    """Quick test - single request."""
    print("Quick Miner Test")
    print("=" * 50)
    
    start_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=start_time,
        time_increment=300,
        time_length=86400,
        num_simulations=1000,
    )
    
    synapse = Simulation(simulation_input=simulation_input)
    
    print(f"Request: {simulation_input.asset}, start_time={start_time[:19]}")
    print("Processing...")
    
    response_tuple, error = await handle_request(synapse)
    
    if error:
        print(f"❌ Error: {error}")
        return False
    
    if response_tuple:
        start_time_unix, time_increment, *paths = response_tuple
        print(f"✅ Success!")
        print(f"   Paths: {len(paths)}")
        print(f"   Path length: {len(paths[0])}")
        print(f"   Path[0] sample: {paths[0][:3]}...")
        print(f"   Path[1] sample: {paths[1][:3]}...")
        return True
    else:
        print("❌ No response")
        return False


if __name__ == "__main__":
    success = asyncio.run(quick_test())
    sys.exit(0 if success else 1)
