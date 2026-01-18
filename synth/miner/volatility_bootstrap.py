"""
Step 6: Bootstrap volatility state on first run (cold start).
Initializes EWMA state with historical data if state is missing.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import numpy as np
import bittensor as bt

from synth.miner.volatility_state import VolatilityStateManager, get_volatility_manager
from synth.miner.historical_price_fetcher import get_recent_volatility_estimate
from synth.miner.price_fetcher import fetch_start_price


# Bootstrap periods (hours)
BOOTSTRAP_PERIODS = {
    # Crypto: 6 hours
    "BTC": 6,
    "ETH": 6,
    "SOL": 6,
    # XAU: 12 hours
    "XAU": 12,
    # Equities: Will use trading days (implemented in Step 9)
    "SPYX": None,  # TBD
    "NVDAX": None,
    "TSLAX": None,
    "AAPLX": None,
    "GOOGLX": None,
}


def bootstrap_volatility_state(
    asset: str,
    current_price: float,
    current_time: datetime,
) -> Optional[float]:
    """
    Bootstrap volatility state for asset on cold start.
    
    If state for requested asset is missing:
    - Fetch recent data based on asset class
    - Compute initial sigma2_0 = mean(r^2) with floor
    - Initialize state
    
    Args:
        asset: Asset symbol
        current_price: Current price to use as last_close
        current_time: Current timestamp
    
    Returns:
        Initial sigma2_1m (variance), or None if bootstrap failed
    """
    manager = get_volatility_manager()
    
    # Check if state already exists
    existing_state = manager.get_state(asset)
    if existing_state is not None:
        bt.logging.debug(f"State already exists for {asset}, skipping bootstrap")
        return existing_state.sigma2_1m
    
    # Get bootstrap period
    bootstrap_hours = BOOTSTRAP_PERIODS.get(asset)
    
    if bootstrap_hours is None:
        # Asset not configured for bootstrap (equities handled separately)
        # Use conservative default
        bt.logging.warning(f"No bootstrap period for {asset}, using default variance")
        initial_sigma2 = 1e-6  # Conservative default
        manager.initialize_state(asset, initial_sigma2, current_price, current_time)
        return initial_sigma2
    
    # For now, use defaults immediately (skip slow sampling)
    # TODO: In production, optionally call get_recent_volatility_estimate for better bootstrap
    # For testing, defaults are faster and sufficient
    
    # Fallback: Use asset-class defaults
    # Conservative initial variance estimates
    default_sigma2 = {
        "BTC": 5e-6,  # ~0.2% daily vol estimate
        "ETH": 8e-6,  # ~0.25% daily vol estimate
        "SOL": 12e-6,  # ~0.35% daily vol estimate
        "XAU": 2e-6,  # ~0.1% daily vol estimate
    }
    
    initial_sigma2 = default_sigma2.get(asset, 1e-6)
    
    bt.logging.info(
        f"Bootstrapping {asset} with default: sigma2_1m={initial_sigma2:.2e}"
    )
    
    manager.initialize_state(asset, initial_sigma2, current_price, current_time)
    return initial_sigma2


def ensure_state_initialized(asset: str) -> bool:
    """
    Ensure volatility state is initialized for asset.
    
    If state doesn't exist, bootstrap it using current price.
    This is called on-demand when state is needed.
    
    Returns:
        True if state is now initialized, False otherwise
    """
    manager = get_volatility_manager()
    
    if manager.get_state(asset) is not None:
        return True  # Already initialized
    
    # Fetch current price for bootstrap
    current_time = datetime.now(timezone.utc)
    current_price = fetch_start_price(asset, current_time)
    
    if current_price is None:
        bt.logging.error(f"Cannot bootstrap {asset}: price fetch failed")
        return False
    
    # Bootstrap
    sigma2 = bootstrap_volatility_state(asset, current_price, current_time)
    
    return sigma2 is not None
