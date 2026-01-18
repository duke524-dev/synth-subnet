"""
Step 8: Step volatility conversion + caps
Converts 1-minute volatility to step volatility with caps.
"""

import math
from typing import Optional
import bittensor as bt

# Default sigma_cap_daily per asset (as annualized percentage, converted internally)
SIGMA_CAP_DAILY = {
    "BTC": 0.10,  # 10% daily cap
    "ETH": 0.12,  # 12% daily cap
    "SOL": 0.18,  # 18% daily cap
    "XAU": 0.03,  # 3% daily cap
    "SPYX": 0.02,  # 2% daily cap
    "NVDAX": 0.04,  # 4% daily cap
    "TSLAX": 0.05,  # 5% daily cap
    "AAPLX": 0.02,  # 2% daily cap
    "GOOGLX": 0.02,  # 2% daily cap
}

# HIGH prompt shrink factor (optional)
SHRINK_HIGH = {
    "BTC": 0.9,
    "ETH": 0.9,
    "SOL": 0.9,
    "XAU": 0.95,
}


def convert_to_step_volatility(
    sigma2_1m: float,
    time_increment: int,
    asset: str,
    is_high_frequency: bool = False,
) -> float:
    """
    Convert 1-minute volatility to step volatility with caps.
    
    Formula:
        sigma_1m = sqrt(sigma2_1m)
        step_minutes = time_increment / 60
        sigma_step = sigma_1m * sqrt(step_minutes)
    
    Apply cap using daily cap:
        sigma_step_cap = sigma_cap_daily / sqrt(1440 / step_minutes)
        sigma_step = min(sigma_step, sigma_step_cap)
    
    Apply floor:
        sigma_step = max(sigma_step, 1e-8)
    
    HIGH prompt optional shrink:
        sigma_step *= shrink_high (e.g., 0.9)
    
    Args:
        sigma2_1m: 1-minute variance
        time_increment: Time increment in seconds
        asset: Asset symbol
        is_high_frequency: Whether this is HIGH frequency prompt
    
    Returns:
        sigma_step: Volatility for the step (in log-returns)
    """
    # Convert 1-minute variance to 1-minute volatility
    sigma_1m = math.sqrt(sigma2_1m)
    
    # Calculate step minutes
    step_minutes = time_increment / 60.0
    
    # Convert to step volatility
    sigma_step = sigma_1m * math.sqrt(step_minutes)
    
    # Apply daily cap
    sigma_cap_daily = SIGMA_CAP_DAILY.get(asset, 0.10)  # Default 10%
    
    # Convert daily cap to step cap
    # Daily has 1440 minutes
    # sigma_step_cap = sigma_cap_daily / sqrt(1440 / step_minutes)
    # This ensures that if sigma_step = sigma_step_cap for all steps, daily vol = sigma_cap_daily
    minutes_per_day = 1440.0
    sigma_step_cap = sigma_cap_daily / math.sqrt(minutes_per_day / step_minutes)
    
    # Apply cap
    sigma_step = min(sigma_step, sigma_step_cap)
    
    # Apply floor (avoid zero volatility)
    sigma_step = max(sigma_step, 1e-8)
    
    # Apply HIGH frequency shrink (optional)
    if is_high_frequency:
        shrink = SHRINK_HIGH.get(asset, 1.0)
        sigma_step *= shrink
    
    return sigma_step


def get_sigma_cap_daily(asset: str) -> float:
    """Get daily volatility cap for asset."""
    return SIGMA_CAP_DAILY.get(asset, 0.10)


def get_shrink_high(asset: str) -> float:
    """Get HIGH frequency shrink factor for asset."""
    return SHRINK_HIGH.get(asset, 1.0)
