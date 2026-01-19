"""
Steps 1-11: Complete request handler with volatility state and path generation
Core request handler that integrates all components.
"""

from datetime import datetime, timezone
from typing import Tuple, Optional
import bittensor as bt
from synth.protocol import Simulation
from synth.simulation_input import SimulationInput

from synth.miner.validator_core import (
    validate_response_local,
    generate_safe_fallback_paths,
)
from synth.miner.price_fetcher import fetch_start_price
from synth.miner.volatility_state import get_volatility_manager
from synth.miner.volatility_bootstrap import ensure_state_initialized
from synth.miner.volatility_scaling import convert_to_step_volatility
from synth.miner.equity_market_hours import apply_equity_flattening
from synth.miner.path_generator import generate_all_paths
from synth.miner.state_persistence import persist_state_if_needed
from synth.miner.prediction_logger import get_prediction_logger


def parse_request(simulation_input: SimulationInput) -> Tuple[int, int, int]:
    """
    Parse request and compute path parameters.
    
    Returns:
        (steps, num_simulations, time_increment)
    """
    steps = simulation_input.time_length // simulation_input.time_increment
    num_simulations = simulation_input.num_simulations
    time_increment = simulation_input.time_increment
    
    return steps, num_simulations, time_increment


def round_to_8_significant_digits(num: float) -> float:
    """Round to 8 significant digits."""
    if num == 0:
        return 0.0
    from math import log10, floor
    magnitude = floor(log10(abs(num)))
    decimal_places = 8 - magnitude - 1
    return round(num, decimal_places)


def generate_dummy_paths(start_price: float, steps: int, num_simulations: int) -> list:
    """
    Generate dummy paths (all flat at start_price) for MVP.
    
    Each path is [start_price, start_price, ..., start_price] (steps + 1 values)
    
    Returns:
        List of num_simulations paths, each of length (steps + 1)
    """
    path_length = steps + 1
    paths = []
    
    for _ in range(num_simulations):
        path = [float(start_price)] * path_length
        paths.append(path)
    
    return paths


def format_response_tuple(price_paths: list, start_time: str, time_increment: int) -> tuple:
    """
    Format price paths into validator-expected tuple format.
    
    Format: (start_time_unix, time_increment, path_1, path_2, ..., path_1000)
    
    Args:
        price_paths: List of price paths (each is list of floats)
        start_time: ISO 8601 string
        time_increment: Time increment in seconds
    
    Returns:
        Tuple in validator format
    """
    # Convert start_time to Unix timestamp
    start_time_dt = datetime.fromisoformat(start_time).replace(tzinfo=timezone.utc)
    start_time_unix = int(start_time_dt.timestamp())
    
    # Round prices to 8 significant digits
    def round_to_8_digits(num: float) -> float:
        """Round to 8 significant digits."""
        if num == 0:
            return 0.0
        from math import log10, floor
        magnitude = floor(log10(abs(num)))
        decimal_places = 8 - magnitude - 1
        return round(num, decimal_places)
    
    # Build response tuple
    result = [start_time_unix, time_increment]
    
    for path in price_paths:
        rounded_path = [round_to_8_digits(float(p)) for p in path]
        result.append(rounded_path)
    
    return tuple(result)


async def handle_request(synapse: Simulation) -> Tuple[Optional[tuple], Optional[str]]:
    """
    Complete request handler (Steps 1-11).
    
    Flow:
    1. Parse request
    2. Update EWMA state using any new 1m closes since last_update_ts
    3. Fetch spot S0 (close at/before start_time)
    4. Compute sigma_step + caps + equity flatten rules
    5. Generate 1000 paths (path0 deterministic + 999 stochastic)
    6. Validate response
    7. Return before start_time
    
    Returns:
        (response_tuple, error_message)
        - If successful: (tuple, None)
        - If failed: (None, error_string)
    """
    simulation_input = synapse.simulation_input
    
    # Step 1: Parse request
    try:
        steps, num_simulations, time_increment = parse_request(simulation_input)
    except Exception as e:
        return None, f"Request parsing failed: {e}"
    
    # Validate request
    if num_simulations != 1000:
        return None, f"Expected 1000 simulations, got {num_simulations}"
    
    if steps <= 0:
        return None, f"Invalid steps: {steps} (time_length={simulation_input.time_length}, time_increment={time_increment})"
    
    # Check timing
    request_time = datetime.now(timezone.utc)
    try:
        start_time_dt = datetime.fromisoformat(simulation_input.start_time).replace(tzinfo=timezone.utc)
    except ValueError as e:
        return None, f"Invalid start_time format: {e}"
    
    if request_time >= start_time_dt:
        return None, f"Request too late: start_time={start_time_dt}, now={request_time}"
    
    asset = simulation_input.asset
    
    # Step 3: Fetch start price from Pyth (with caching fallback)
    raw_start_price = fetch_start_price(asset, start_time_dt)
    
    if raw_start_price is None:
        bt.logging.warning(f"Price fetch failed for {asset}, using fallback")
        raw_start_price = 1.0  # Ultimate fallback
    
    # Round price to 8 significant digits
    start_price = round_to_8_significant_digits(raw_start_price)
    
    # Step 5-6: Ensure volatility state is initialized
    manager = get_volatility_manager()
    state_initialized = ensure_state_initialized(asset)
    
    if not state_initialized:
        bt.logging.warning(f"Failed to initialize state for {asset}, using flat paths")
        # Fallback to flat paths
        price_paths = generate_dummy_paths(start_price, steps, num_simulations)
    else:
        # Step 5: Update EWMA state with current price
        # Use the fetched start_price as a proxy for 1-minute close
        # Note: This is an approximation - ideally we'd fetch true 1-minute closes
        # but Pyth API limitations make this challenging
        current_time = datetime.now(timezone.utc)
        
        # Only update if we have a valid state and price
        if start_price > 0:
            manager.update_state(asset, start_price, current_time)
            bt.logging.debug(
                f"Updated volatility state for {asset} using start_price={start_price:.2f}"
            )
        else:
            bt.logging.warning(
                f"Skipping volatility update for {asset}: invalid start_price={start_price}"
            )
        
        # Get sigma2_1m
        sigma2_1m = manager.get_sigma2_1m(asset)
        if sigma2_1m is None:
            bt.logging.warning(f"No sigma2_1m for {asset}, using flat paths")
            price_paths = generate_dummy_paths(start_price, steps, num_simulations)
        else:
            # Step 8: Convert to step volatility with caps
            # Determine if HIGH frequency (60s increment, 3600s length)
            is_high_frequency = (
                simulation_input.time_increment == 60 and
                simulation_input.time_length == 3600
            )
            
            sigma_step = convert_to_step_volatility(
                sigma2_1m=sigma2_1m,
                time_increment=time_increment,
                asset=asset,
                is_high_frequency=is_high_frequency,
            )
            
            # Step 9: Apply equity flattening (LOW prompt only)
            if not is_high_frequency:
                sigma_step = apply_equity_flattening(sigma_step, asset, start_time_dt)
            
            # Step 10: Generate all 1000 paths
            try:
                price_paths = generate_all_paths(
                    start_price=start_price,
                    steps=steps,
                    sigma_step=sigma_step,
                    asset=asset,
                    num_simulations=1000,
                )
            except Exception as e:
                bt.logging.error(f"Path generation failed: {e}", exc_info=True)
                # Fallback to flat paths
                price_paths = generate_dummy_paths(start_price, steps, num_simulations)
            
            # Step 7: Persist state if needed (non-blocking)
            try:
                persist_state_if_needed(asset, force=False)
            except Exception as e:
                bt.logging.warning(f"State persistence failed: {e}")
    
    # Step 2: Validate response before sending
    validation_error = validate_response_local(
        price_paths=price_paths,
        simulation_input=simulation_input,
        start_price=start_price,
    )
    
    if validation_error:
        bt.logging.warning(f"Validation failed, using safe fallback: {validation_error}")
        price_paths = generate_safe_fallback_paths(start_price, steps, num_simulations)
        
        validation_error = validate_response_local(
            price_paths=price_paths,
            simulation_input=simulation_input,
            start_price=start_price,
        )
        
        if validation_error:
            return None, f"Fallback paths also invalid: {validation_error}"
    
    # Format response tuple
    response_tuple = format_response_tuple(
        price_paths=price_paths,
        start_time=simulation_input.start_time,
        time_increment=time_increment,
    )
    
    # Final timing check
    final_time = datetime.now(timezone.utc)
    if final_time >= start_time_dt:
        return None, f"Response generation took too long: {final_time} >= {start_time_dt}"
    
    elapsed = (final_time - request_time).total_seconds()
    time_until_start = (start_time_dt - request_time).total_seconds()
    
    # Step 13: Log prediction (sampling strategy applied)
    try:
        logger = get_prediction_logger()
        
        # Get current config snapshot for logging
        manager = get_volatility_manager()
        state = manager.get_state(asset)
        
        # Import parameter getters to get actual values (including tuned values)
        from synth.miner.path_generator import get_student_t_df
        from synth.miner.volatility_scaling import get_sigma_cap_daily, get_shrink_high
        
        config_snapshot = {
            'lambda': state.lambda_val if state else None,
            'df': get_student_t_df(asset),
            'sigma_cap_daily': get_sigma_cap_daily(asset),
            'shrink_high': get_shrink_high(asset),
        }
        
        logger.log_prediction(
            simulation_input=simulation_input,
            price_paths=price_paths,
            config=config_snapshot,
            request_time=request_time,
            volatility_spike=False,  # TODO: Implement spike detection in future
            equity_market_event=False,  # TODO: Implement market event detection in future
        )
    except Exception as e:
        # Don't fail request if logging fails
        bt.logging.warning(f"Prediction logging failed: {e}")
    
    bt.logging.info(
        f"Generated response - asset={asset}, paths={len(price_paths)}, "
        f"path_length={len(price_paths[0])}, start_price={start_price:.2f}, "
        f"elapsed={elapsed:.2f}s, remaining={time_until_start-elapsed:.2f}s"
    )
    
    return response_tuple, None


# Alias for backward compatibility
async def handle_request_step1_3(synapse: Simulation) -> Tuple[Optional[tuple], Optional[str]]:
    """Alias for handle_request (backward compatibility)."""
    return await handle_request(synapse)
