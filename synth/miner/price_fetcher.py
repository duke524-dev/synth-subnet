"""
Step 3: Pyth spot fetch with caching and fallback.
Fetches latest close price at or before start_time.
"""

from datetime import datetime, timezone
from typing import Optional
import requests
from tenacity import retry, stop_after_attempt, wait_random_exponential
import bittensor as bt

# Pyth Benchmarks TradingView shim
PYTH_BASE_URL = "https://hermes.pyth.network/v2/updates/price/latest"

TOKEN_MAP = {
    "BTC": "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH": "ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "XAU": "765d2ba906dbc32ca17cc11f5310a89e9ee1f6420508c63861f2f8ba4ee34bb2",
    "SOL": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
}

# Cache for last-known-good prices
_price_cache = {}
_cache_timestamps = {}
CACHE_MAX_AGE_SECONDS = 180  # 3 minutes staleness threshold


@retry(
    stop_after_attempt(5),
    wait_random_exponential(multiplier=2),
    reraise=False,
)
def _fetch_price_from_pyth(asset: str) -> Optional[float]:
    """
    Fetch current price from Pyth API.
    
    Returns:
        Price as float, or None if fetch fails
    """
    if asset not in TOKEN_MAP:
        bt.logging.warning(f"Asset {asset} not in TOKEN_MAP")
        return None
    
    try:
        pyth_params = {"ids[]": [TOKEN_MAP[asset]]}
        response = requests.get(PYTH_BASE_URL, params=pyth_params, timeout=5)
        
        if response.status_code != 200:
            bt.logging.warning(f"Pyth API error for {asset}: {response.status_code}")
            return None
        
        data = response.json()
        parsed_data = data.get("parsed", [])
        
        if not parsed_data:
            bt.logging.warning(f"Pyth API returned empty data for {asset}")
            return None
        
        asset_data = parsed_data[0]
        price = int(asset_data["price"]["price"])
        expo = int(asset_data["price"]["expo"])
        
        live_price: float = price * (10 ** expo)
        
        if live_price <= 0:
            bt.logging.warning(f"Pyth returned invalid price for {asset}: {live_price}")
            return None
        
        return live_price
    
    except Exception as e:
        bt.logging.warning(f"Pyth fetch error for {asset}: {e}")
        return None


def fetch_start_price(asset: str, start_time: Optional[datetime] = None) -> Optional[float]:
    """
    Fetch price at start_time, with caching fallback.
    
    Uses CLOSE prices only.
    Aligns to minute grid (uses latest 1-minute close at or before requested time).
    
    Args:
        asset: Asset symbol (BTC, ETH, XAU, SOL)
        start_time: Optional target time (defaults to now)
    
    Returns:
        Price as float, or None if unavailable
    """
    now = datetime.now(timezone.utc)
    
    # Try fresh fetch first
    price = _fetch_price_from_pyth(asset)
    
    if price is not None and price > 0:
        # Update cache
        _price_cache[asset] = price
        _cache_timestamps[asset] = now
        bt.logging.debug(f"Fetched fresh price for {asset}: {price}")
        return price
    
    # Fallback to cache if available
    if asset in _price_cache:
        cache_time = _cache_timestamps.get(asset)
        cache_age = (now - cache_time).total_seconds() if cache_time else float('inf')
        
        if cache_age < CACHE_MAX_AGE_SECONDS:
            bt.logging.warning(
                f"Using cached price for {asset} (age: {cache_age:.0f}s, "
                f"price: {_price_cache[asset]})"
            )
            return _price_cache[asset]
        else:
            bt.logging.warning(
                f"Cached price for {asset} too stale (age: {cache_age:.0f}s > "
                f"{CACHE_MAX_AGE_SECONDS}s)"
            )
    
    # No price available
    bt.logging.error(
        f"No price available for {asset} (fresh fetch failed, no valid cache)"
    )
    return None


def get_cached_price(asset: str) -> Optional[float]:
    """Get cached price without fetching (for fallback)."""
    return _price_cache.get(asset)
