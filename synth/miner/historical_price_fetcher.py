"""
Step 4: 1-minute OHLC close fetch for state updates.
Fetches historical 1-minute close prices for EWMA volatility calculation.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional
import requests
import bittensor as bt

from synth.miner.price_fetcher import TOKEN_MAP

# Note: Pyth may not have direct historical endpoint
# This implementation uses the latest endpoint and relies on incremental updates
# For historical bootstrap, we'll need to handle it differently

PYTH_BASE_URL = "https://hermes.pyth.network/v2/updates/price/latest"


def floor_to_minute(dt: datetime) -> datetime:
    """Floor timestamp to minute grid (remove seconds/microseconds)."""
    return dt.replace(second=0, microsecond=0)


def fetch_1m_closes(
    asset: str,
    end_ts: datetime,
    lookback_minutes: int,
) -> List[Tuple[datetime, float]]:
    """
    Fetch 1-minute close prices for EWMA bootstrap.
    
    Rules:
    - close only
    - floor timestamps to minute grid
    - do not interpolate
    - missing minutes are allowed (skip them)
    
    Args:
        asset: Asset symbol
        end_ts: End timestamp
        lookback_minutes: How many minutes to look back
    
    Returns:
        List of (timestamp, close_price) tuples
        Timestamps are floored to minute grid
    
    Note: Pyth API doesn't provide direct historical access.
    This function is a placeholder for when we have historical data source.
    For now, we'll bootstrap using current price and recent volatility estimate.
    """
    if asset not in TOKEN_MAP:
        bt.logging.warning(f"Asset {asset} not supported for historical fetch")
        return []
    
    # For now, return empty list - bootstrap will use alternative method
    # TODO: Implement when historical data source is available
    bt.logging.debug(
        f"Historical fetch requested: asset={asset}, "
        f"end={end_ts}, lookback={lookback_minutes}min"
    )
    
    return []


def get_recent_volatility_estimate(asset: str, minutes: int = 60) -> Optional[float]:
    """
    Get a rough volatility estimate from recent price movements.
    
    This is a fallback when historical 1-minute data is not available.
    Uses multiple price fetches over time to estimate volatility.
    
    Args:
        asset: Asset symbol
        minutes: How many minutes to sample (max 5-10 due to API rate limits)
    
    Returns:
        Estimated sigma2_1m (variance of 1-minute returns), or None if unavailable
    """
    # Limit to reasonable sampling (5-10 points to avoid rate limits)
    sample_count = min(minutes, 10)
    sample_interval = max(1, minutes // sample_count)
    
    prices = []
    timestamps = []
    
    for i in range(sample_count):
        from synth.miner.price_fetcher import _fetch_price_from_pyth
        import time
        
        price = _fetch_price_from_pyth(asset)
        if price is not None and price > 0:
            prices.append(price)
            timestamps.append(datetime.now(timezone.utc))
        
        if i < sample_count - 1:  # Don't sleep after last sample
            time.sleep(sample_interval)  # Space out requests
    
    if len(prices) < 2:
        return None
    
    # Calculate returns
    import numpy as np
    returns = []
    for i in range(1, len(prices)):
        if prices[i-1] > 0:
            r = np.log(prices[i] / prices[i-1])
            returns.append(r)
    
    if len(returns) == 0:
        return None
    
    # Estimate variance (convert from sample interval to 1-minute)
    returns_array = np.array(returns)
    sample_variance = np.var(returns_array)
    
    # Scale to 1-minute variance (assuming sample_interval minutes between samples)
    # If samples are N minutes apart, scale by 1/N
    if len(returns) > 0:
        avg_interval = sample_interval  # Rough estimate
        sigma2_1m = sample_variance / avg_interval
    else:
        sigma2_1m = sample_variance
    
    # Apply floor
    sigma2_1m = max(sigma2_1m, 1e-8)
    
    return float(sigma2_1m)
