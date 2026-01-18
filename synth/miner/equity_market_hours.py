"""
Step 9: Equity market-hours flattening (LOW prompt)
Handles equity trading hours - forces flat paths outside market hours.
"""

from datetime import datetime, timezone
from typing import Set


EQUITY_ASSETS: Set[str] = {
    "SPYX",
    "NVDAX",
    "TSLAX",
    "AAPLX",
    "GOOGLX",
}

# NYSE trading hours in UTC
# Approximate: 14:30 - 21:00 UTC (9:30 AM - 4:00 PM EST)
MARKET_OPEN_HOUR_UTC = 14
MARKET_OPEN_MINUTE_UTC = 30
MARKET_CLOSE_HOUR_UTC = 21
MARKET_CLOSE_MINUTE_UTC = 0


def is_equity(asset: str) -> bool:
    """Check if asset is an equity."""
    return asset in EQUITY_ASSETS


def is_market_hours( timestamp: datetime) -> bool:
    """
    Check if timestamp is within NYSE trading hours.
    
    Trading days: Monday-Friday (0-4)
    Trading hours: 14:30-21:00 UTC (approximate)
    
    Args:
        timestamp: Timestamp to check
    
    Returns:
        True if within market hours, False otherwise
    """
    # Check if weekday (Monday=0, Friday=4)
    weekday = timestamp.weekday()
    if weekday >= 5:  # Saturday or Sunday
        return False
    
    # Check if within trading hours
    hour = timestamp.hour
    minute = timestamp.minute
    
    # Before market open
    if hour < MARKET_OPEN_HOUR_UTC:
        return False
    if hour == MARKET_OPEN_HOUR_UTC and minute < MARKET_OPEN_MINUTE_UTC:
        return False
    
    # After market close
    if hour > MARKET_CLOSE_HOUR_UTC:
        return False
    if hour == MARKET_CLOSE_HOUR_UTC and minute >= MARKET_CLOSE_MINUTE_UTC:
        return False
    
    return True


def should_flatten_equity(asset: str, start_time: datetime) -> bool:
    """
    Determine if equity should have flattened volatility.
    
    For equities during LOW prompt:
    - If market closed: force sigma_step ≈ 0
    - Paths remain flat (deterministic / near deterministic)
    
    Args:
        asset: Asset symbol
        start_time: Start time of forecast
    
    Returns:
        True if should flatten (market closed), False otherwise
    """
    if not is_equity(asset):
        return False  # Only equities need flattening
    
    # Check if market is closed at start_time
    return not is_market_hours(start_time)


def apply_equity_flattening(
    sigma_step: float,
    asset: str,
    start_time: datetime,
) -> float:
    """
    Apply equity market-hours flattening.
    
    If market closed: force sigma_step ≈ 0
    
    Args:
        sigma_step: Current step volatility
        asset: Asset symbol
        start_time: Start time of forecast
    
    Returns:
        Flattened sigma_step (very small if market closed)
    """
    if should_flatten_equity(asset, start_time):
        # Force very small volatility (near flat paths)
        return 1e-8  # Near zero
    else:
        return sigma_step
