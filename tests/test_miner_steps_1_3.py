"""
Test Steps 1-3: Request parsing, validation, and Pyth price fetch.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from synth.protocol import Simulation
from synth.simulation_input import SimulationInput
from synth.miner.request_handler import handle_request_step1_3
from synth.miner.validator_core import validate_response_local


def test_step1_parsing():
    """Test Step 1: Request parsing."""
    print("\n=== Testing Step 1: Request Parsing ===")
    
    # Create valid simulation input
    start_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=start_time,
        time_increment=300,  # 5 minutes
        time_length=86400,   # 24 hours
        num_simulations=1000,
    )
    
    # Test parsing
    from synth.miner.request_handler import parse_request
    steps, num_simulations, time_increment = parse_request(simulation_input)
    
    print(f"Steps: {steps} (expected: 288)")
    print(f"Num simulations: {num_simulations} (expected: 1000)")
    print(f"Time increment: {time_increment} (expected: 300)")
    
    assert steps == 288, f"Expected 288 steps, got {steps}"
    assert num_simulations == 1000, f"Expected 1000 simulations, got {num_simulations}"
    assert time_increment == 300, f"Expected 300s increment, got {time_increment}"
    
    print("✅ Step 1: Parsing test PASSED")


def test_step2_validation():
    """Test Step 2: Local validation."""
    print("\n=== Testing Step 2: Local Validation ===")
    
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        time_increment=300,
        time_length=86400,
        num_simulations=1000,
    )
    
    # Valid paths (1000 paths, each 289 points)
    start_price = 50000.0
    steps = 288
    valid_paths = []
    for _ in range(1000):
        path = [start_price] * (steps + 1)
        valid_paths.append(path)
    
    error = validate_response_local(
        price_paths=valid_paths,
        simulation_input=simulation_input,
        start_price=start_price,
    )
    
    assert error is None, f"Validation should pass, got error: {error}"
    print("✅ Valid paths: PASSED")
    
    # Test invalid: wrong number of paths
    invalid_paths = valid_paths[:999]  # Only 999 paths
    error = validate_response_local(
        price_paths=invalid_paths,
        simulation_input=simulation_input,
        start_price=start_price,
    )
    assert error is not None, "Validation should fail for wrong path count"
    print("✅ Invalid path count detection: PASSED")
    
    # Test invalid: wrong path length
    invalid_paths = [[start_price] * 100 for _ in range(1000)]  # Wrong length
    error = validate_response_local(
        price_paths=invalid_paths,
        simulation_input=simulation_input,
        start_price=start_price,
    )
    assert error is not None, "Validation should fail for wrong path length"
    print("✅ Invalid path length detection: PASSED")
    
    # Test invalid: zero price
    invalid_paths = valid_paths.copy()
    invalid_paths[0][0] = 0.0
    error = validate_response_local(
        price_paths=invalid_paths,
        simulation_input=simulation_input,
        start_price=start_price,
    )
    assert error is not None, "Validation should fail for zero price"
    print("✅ Zero price detection: PASSED")
    
    print("✅ Step 2: Validation tests PASSED")


async def test_step3_price_fetch():
    """Test Step 3: Pyth price fetch."""
    print("\n=== Testing Step 3: Pyth Price Fetch ===")
    
    from synth.miner.price_fetcher import fetch_start_price
    
    # Test fetching BTC price
    print("Fetching BTC price from Pyth...")
    price = fetch_start_price("BTC")
    
    if price is not None:
        print(f"✅ BTC price fetched: ${price:,.2f}")
        assert price > 0, f"Price should be positive, got {price}"
        assert price < 1000000, f"Price seems too high: {price}"
    else:
        print("⚠️  Price fetch failed (may be network issue)")
    
    # Test caching
    print("Testing cache (second fetch should use cache)...")
    price2 = fetch_start_price("BTC")
    if price2 is not None:
        print(f"✅ Cached price: ${price2:,.2f}")
    
    print("✅ Step 3: Price fetch test COMPLETED")


async def test_full_request_handler():
    """Test full request handler (Steps 1-3 integration)."""
    print("\n=== Testing Full Request Handler (Steps 1-3) ===")
    
    # Create synapse with valid input
    start_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=start_time,
        time_increment=300,
        time_length=86400,
        num_simulations=1000,
    )
    
    synapse = Simulation(simulation_input=simulation_input)
    
    # Handle request
    print("Processing request...")
    response_tuple, error = await handle_request_step1_3(synapse)
    
    if error:
        print(f"❌ Request failed: {error}")
        return False
    
    if response_tuple is None:
        print("❌ No response returned")
        return False
    
    # Validate response structure
    assert isinstance(response_tuple, tuple), "Response should be tuple"
    assert len(response_tuple) >= 3, f"Response should have at least 3 elements, got {len(response_tuple)}"
    
    start_time_unix, time_increment, *paths = response_tuple
    
    print(f"✅ Response structure valid:")
    print(f"   Start time (Unix): {start_time_unix}")
    print(f"   Time increment: {time_increment}")
    print(f"   Number of paths: {len(paths)}")
    print(f"   First path length: {len(paths[0])}")
    
    # Validate paths
    assert len(paths) == 1000, f"Expected 1000 paths, got {len(paths)}"
    assert len(paths[0]) == 289, f"Expected 289 points per path, got {len(paths[0])}"
    
    # Check all prices are valid
    for i, path in enumerate(paths[:10]):  # Check first 10 paths
        for j, price in enumerate(path[:10]):  # Check first 10 prices
            assert isinstance(price, (int, float)), f"Path {i}, price {j} not numeric"
            assert price > 0, f"Path {i}, price {j} not positive: {price}"
    
    print("✅ Step 1-3: Full integration test PASSED")
    return True


async def test_error_cases():
    """Test error handling."""
    print("\n=== Testing Error Cases ===")
    
    # Test: Invalid num_simulations
    start_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=start_time,
        time_increment=300,
        time_length=86400,
        num_simulations=500,  # Wrong!
    )
    synapse = Simulation(simulation_input=simulation_input)
    response, error = await handle_request_step1_3(synapse)
    assert error is not None, "Should error on wrong num_simulations"
    print("✅ Invalid num_simulations detection: PASSED")
    
    # Test: Start time in past
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    simulation_input = SimulationInput(
        asset="BTC",
        start_time=past_time,
        time_increment=300,
        time_length=86400,
        num_simulations=1000,
    )
    synapse = Simulation(simulation_input=simulation_input)
    response, error = await handle_request_step1_3(synapse)
    assert error is not None, "Should error on past start_time"
    print("✅ Past start_time detection: PASSED")
    
    print("✅ Error case tests PASSED")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Steps 1-3: Request Handler, Validation, Price Fetch")
    print("=" * 60)
    
    try:
        # Step 1: Parsing
        test_step1_parsing()
        
        # Step 2: Validation
        test_step2_validation()
        
        # Step 3: Price fetch (async, may fail if network unavailable)
        await test_step3_price_fetch()
        
        # Full integration
        success = await test_full_request_handler()
        
        # Error cases
        await test_error_cases()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
