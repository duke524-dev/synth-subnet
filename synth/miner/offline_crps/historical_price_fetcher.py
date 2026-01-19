"""
Historical price fetcher for offline CRPS replay.
Fetches realized prices from Pyth for a given time period.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
import numpy as np
import requests
import bittensor as bt
from tenacity import (
    before_log,
    retry,
    stop_after_attempt,
    wait_random_exponential,
)
import logging

from synth.miner.price_fetcher import TOKEN_MAP
from synth.utils.helpers import from_iso_to_unix_time

# Pyth API benchmarks doc: https://benchmarks.pyth.network/docs
BASE_URL = "https://benchmarks.pyth.network/v1/shims/tradingview/history"

# Token mapping for Pyth benchmarks API
PYTH_TOKEN_MAP = {
    "BTC": "Crypto.BTC/USD",
    "ETH": "Crypto.ETH/USD",
    "XAU": "Crypto.XAUT/USD",
    "SOL": "Crypto.SOL/USD",
    "SPYX": "Crypto.SPYX/USD",
    "NVDAX": "Crypto.NVDAX/USD",
    "TSLAX": "Crypto.TSLAX/USD",
    "AAPLX": "Crypto.AAPLX/USD",
    "GOOGLX": "Crypto.GOOGLX/USD",
}

# Simple in-memory cache for historical prices to avoid repeated API calls.
# Key: (asset, start_time_unix, time_length, time_increment)
_PRICE_CACHE: dict[tuple[str, int, int, int], np.ndarray] = {}


@retry(
    stop=stop_after_attempt(5),
    wait=wait_random_exponential(multiplier=7),
    reraise=True,
    before=before_log(bt.logging._logger, logging.DEBUG),
)
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
    if asset not in PYTH_TOKEN_MAP:
        bt.logging.warning(f"Asset {asset} not supported for historical price fetching")
        return None

    # Convert to Unix timestamps and build cache key
    start_time_int = int(start_time.timestamp())
    cache_key = (asset, start_time_int, time_length, time_increment)

    # Fast path: return cached prices if available
    cached = _PRICE_CACHE.get(cache_key)
    if cached is not None:
        # Return a copy so callers can't accidentally mutate the cache
        return cached.copy()
    
    try:
        end_time_int = start_time_int + time_length
        
        # OPTIMIZATION: Use grid resolution instead of 1-second resolution
        # This fetches only the candles we need, not all 1-second data
        # Pyth API minimum resolution is typically 60 seconds
        resolution = max(time_increment, 60)
        
        # Prepare API request - fetch only at grid resolution
        params = {
            "symbol": PYTH_TOKEN_MAP[asset],
            "resolution": resolution,  # Use grid resolution, not 1 second
            "from": start_time_int,
            "to": end_time_int,
        }
        
        # Fetch data from Pyth benchmarks API
        response = requests.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Transform data to align with grid
        steps = time_length // time_increment
        num_points = steps + 1
        
        aligned_prices = _transform_pyth_data(
            data,
            start_time_int,
            time_increment,
            time_length,
            num_points,
            resolution,  # Pass resolution to transformation
        )
        
        if aligned_prices is None or len(aligned_prices) != num_points:
            bt.logging.warning(
                f"Price alignment failed for {asset}: "
                f"expected {num_points} points, got {len(aligned_prices) if aligned_prices is not None else 0}"
            )
            return None
        
        prices = np.array(aligned_prices, dtype=np.float64)

        # Store in cache and return a copy
        _PRICE_CACHE[cache_key] = prices
        return prices.copy()
    
    except requests.exceptions.RequestException as e:
        bt.logging.warning(
            f"Failed to fetch historical prices for {asset} from {start_time}: {e}"
        )
        return None
    except Exception as e:
        bt.logging.error(
            f"Error processing historical prices for {asset}: {e}", exc_info=True
        )
        return None


def _transform_pyth_data(
    data: dict,
    start_time_int: int,
    time_increment: int,
    time_length: int,
    num_points: int,
    resolution: int,
) -> Optional[List[float]]:
    """
    Transform Pyth API response to aligned price grid.
    
    Similar to PriceDataProvider._transform_data but returns list of floats.
    
    Args:
        data: Pyth API response data
        start_time_int: Start time as Unix timestamp
        time_increment: Time increment in seconds (grid spacing)
        time_length: Total time length in seconds
        num_points: Expected number of grid points
        resolution: Resolution of fetched candles (seconds)
    """
    if data is None or len(data) == 0 or "t" not in data or len(data["t"]) == 0:
        return None
    
    # Create exact grid timestamps we need
    time_end_int = start_time_int + time_length
    grid_timestamps = [
        t
        for t in range(
            start_time_int, time_end_int + time_increment, time_increment
        )
    ]
    
    # Adjust if needed (same logic as PriceDataProvider)
    if len(grid_timestamps) != num_points:
        if len(grid_timestamps) == num_points + 1:
            if data["t"][-1] < grid_timestamps[1]:
                grid_timestamps = grid_timestamps[:-1]
            elif data["t"][0] > grid_timestamps[0]:
                grid_timestamps = grid_timestamps[1:]
        else:
            return None
    
    # Create price dictionary from API response
    # API returns candles at 'resolution' intervals
    close_prices_dict = {t: c for t, c in zip(data["t"], data["c"])}
    
    # Align prices to exact grid
    aligned_prices = [np.nan for _ in range(len(grid_timestamps))]
    
    for idx, grid_t in enumerate(grid_timestamps):
        # First try exact match
        if grid_t in close_prices_dict:
            aligned_prices[idx] = float(close_prices_dict[grid_t])
        else:
            # Fallback: find closest candle within tolerance
            # This handles cases where API timestamps don't exactly match grid
            # (e.g., due to API timing differences or missing data points)
            tolerance = time_increment
            closest_t = min(
                close_prices_dict.keys(),
                key=lambda t: abs(t - grid_t),
                default=None
            )
            if closest_t is not None and abs(closest_t - grid_t) <= tolerance:
                aligned_prices[idx] = float(close_prices_dict[closest_t])
    
    return aligned_prices


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
