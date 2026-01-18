"""
Step 2: Strict local validation guard (pre-send)
Validates response before sending to validator.
"""

from datetime import datetime
from typing import Optional, List
import numpy as np

from synth.simulation_input import SimulationInput


def validate_response_local(
    price_paths: List[List[float]],
    simulation_input: SimulationInput,
    start_price: float,
) -> Optional[str]:
    """
    Validate response before sending to validator.
    
    Checks:
    - num_paths == 1000
    - each path length is exactly steps + 1
    - all values are finite and > 0
    - no NaN, no 0
    - dtype float64 in internal arrays (implicit, Python uses float64)
    
    Returns:
        None if valid, error message string if invalid
    """
    # Check number of paths
    if len(price_paths) != simulation_input.num_simulations:
        return (
            f"Wrong number of paths: {len(price_paths)} != "
            f"{simulation_input.num_simulations}"
        )
    
    # Calculate expected path length
    steps = simulation_input.time_length // simulation_input.time_increment
    expected_path_length = steps + 1
    
    # Validate each path
    for i, path in enumerate(price_paths):
        # Check path is list/array
        if not isinstance(path, (list, tuple, np.ndarray)):
            return f"Path {i} is not list/tuple/array: {type(path)}"
        
        # Convert to list for easier validation
        path_list = list(path)
        
        # Check path length
        if len(path_list) != expected_path_length:
            return (
                f"Path {i} wrong length: {len(path_list)} != "
                f"{expected_path_length} (steps={steps}, time_length="
                f"{simulation_input.time_length}, time_increment="
                f"{simulation_input.time_increment})"
            )
        
        # Check all prices are valid
        for j, price in enumerate(path_list):
            # Check numeric
            if not isinstance(price, (int, float, np.number)):
                return f"Path {i}, index {j} not numeric: {type(price)} = {price}"
            
            price_float = float(price)
            
            # Check NaN/Inf
            if np.isnan(price_float) or np.isinf(price_float):
                return f"Path {i}, index {j} NaN/Inf: {price_float}"
            
            # Check finite
            if not np.isfinite(price_float):
                return f"Path {i}, index {j} not finite: {price_float}"
            
            # Check positive (strictly > 0)
            if price_float <= 0:
                return f"Path {i}, index {j} not positive: {price_float}"
            
            # Check significant digits (≤8)
            # Remove decimal point and minus sign for digit count
            price_str = str(abs(price_float)).replace(".", "")
            # Remove leading zeros (but keep at least one digit)
            price_str = price_str.lstrip('0') or '0'
            if len(price_str) > 8:
                return (
                    f"Path {i}, index {j} too many significant digits: "
                    f"{price_float} has {len(price_str)} digits (max 8)"
                )
        
        # Check first price matches start_price (allow 1% tolerance)
        first_price = float(path_list[0])
        if abs(first_price - start_price) / start_price > 0.01:
            return (
                f"Path {i} first price mismatch: {first_price} vs "
                f"{start_price} (tolerance exceeded)"
            )
    
    return None


def generate_safe_fallback_paths(start_price: float, steps: int, num_simulations: int) -> list:
    """
    Generate safe fallback paths (all flat) if validation fails.
    
    Returns:
        List of flat paths, all values equal to start_price
    """
    path_length = steps + 1
    paths = []
    
    # Ensure start_price is valid
    if not np.isfinite(start_price) or start_price <= 0:
        start_price = 1.0  # Ultimate fallback
    
    for _ in range(num_simulations):
        path = [float(start_price)] * path_length
        paths.append(path)
    
    return paths
