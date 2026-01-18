"""
Historical price fetcher for offline CRPS replay.
Fetches realized prices from Pyth for a given time period.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
import numpy as np
import requests
import bittensor as bt

from synth.miner.price_fetcher import TOKEN_MAP

# Note: Pyth API may not have direct historical endpoints
# This is a placeholder for when historical data access is available


def fetch_realized_prices(
    asset: str,
    start_time: datetime,
    time_length: int,
    time_increment: int,
) -> Optional[np.ndarray]:
    """
    Fetch realized prices from Pyth for offline CRPS calculation.
    
    Aligns prices to exact grid: t0, t0+increment, t0+2*increment, ...
    
    Args:
        asset: Asset symbol
        start_time: Start time (t0)
        time_length: Total time length in seconds
        time_increment: Time increment in seconds
    
    Returns:
        Array of realized prices aligned to grid, or None if unavailable
        Shape: (steps+1,) where steps = time_length // time_increment
    """
    if asset not in TOKEN_MAP:
        bt.logging.warning(f"Asset {asset} not supported")
        return None
    
    steps = time_length // time_increment
    num_points = steps + 1
    
    # For now, return None - requires historical data source
    # TODO: Implement when historical Pyth data access is available
    bt.logging.warning(
        f"Historical price fetching not yet implemented for {asset} "
        f"from {start_time} over {time_length}s"
    )
    
    return None


def align_prices_to_grid(
    prices: List[Tuple[datetime, float]],
    start_time: datetime,
    time_increment: int,
    num_points: int,
) -> Optional[np.ndarray]:
    """
    Align prices to exact grid points.
    
    Grid: t0, t0+increment, t0+2*increment, ..., t0+steps*increment
    
    Args:
        prices: List of (timestamp, price) tuples
        start_time: Start time (t0)
        time_increment: Time increment in seconds
        num_points: Number of grid points (steps+1)
    
    Returns:
        Array of prices aligned to grid, with NaN for missing points
    """
    # Create grid timestamps
    grid_times = [
        start_time + timedelta(seconds=i * time_increment)
        for i in range(num_points)
    ]
    
    # Create price dictionary for lookup
    price_dict = {ts: price for ts, price in prices}
    
    # Align to grid
    aligned_prices = np.full(num_points, np.nan, dtype=np.float64)
    
    for i, grid_time in enumerate(grid_times):
        # Find closest price (within tolerance)
        tolerance = timedelta(seconds=time_increment / 2)
        
        best_match = None
        best_diff = None
        
        for price_time, price in prices:
            diff = abs((price_time - grid_time).total_seconds())
            if diff <= tolerance.total_seconds():
                if best_match is None or diff < best_diff:
                    best_match = price
                    best_diff = diff
        
        if best_match is not None:
            aligned_prices[i] = float(best_match)
    
    return aligned_prices
