"""
Step 5: EWMA volatility state (the real "model")
Maintains per-asset volatility state using Exponential Weighted Moving Average.
"""

from datetime import datetime, timezone
from typing import Dict, Optional
import numpy as np
import bittensor as bt
from dataclasses import dataclass


@dataclass
class VolatilityState:
    """Per-asset volatility state."""
    asset: str
    sigma2_1m: float  # 1-minute variance (EWMA)
    last_close_1m: float  # Last 1-minute close price
    last_update_ts: datetime  # Timestamp of last update
    lambda_val: float  # EWMA decay parameter
    state_version: int = 1  # For migration support


# Default lambda values per asset class
DEFAULT_LAMBDA = {
    # Crypto
    "BTC": 0.94,
    "ETH": 0.93,
    "SOL": 0.90,
    # XAU
    "XAU": 0.97,
    # Equities (will be added later)
    "SPYX": 0.98,
    "NVDAX": 0.97,
    "TSLAX": 0.97,
    "AAPLX": 0.98,
    "GOOGLX": 0.98,
}


class VolatilityStateManager:
    """
    Manages EWMA volatility state for all assets.
    
    Per asset maintains:
    - sigma2_1m
    - last_close_1m
    - last_update_ts
    
    Update rule:
        r_t = log(close_t / close_{t-1})
        sigma2 = lambda * sigma2 + (1 - lambda) * r_t^2
    """
    
    def __init__(self):
        self._states: Dict[str, VolatilityState] = {}
    
    def get_lambda(self, asset: str) -> float:
        """Get lambda (decay parameter) for asset."""
        return DEFAULT_LAMBDA.get(asset, 0.95)  # Default fallback
    
    def initialize_state(
        self,
        asset: str,
        initial_sigma2: float,
        initial_close: float,
        timestamp: datetime,
    ) -> VolatilityState:
        """
        Initialize volatility state for an asset.
        
        Args:
            asset: Asset symbol
            initial_sigma2: Initial 1-minute variance estimate
            initial_close: Initial close price
            timestamp: Initial timestamp
        """
        lambda_val = self.get_lambda(asset)
        
        state = VolatilityState(
            asset=asset,
            sigma2_1m=initial_sigma2,
            last_close_1m=initial_close,
            last_update_ts=timestamp,
            lambda_val=lambda_val,
        )
        
        self._states[asset] = state
        return state
    
    def get_state(self, asset: str) -> Optional[VolatilityState]:
        """Get volatility state for asset."""
        return self._states.get(asset)
    
    def update_state(
        self,
        asset: str,
        new_close: float,
        timestamp: datetime,
    ) -> VolatilityState:
        """
        Update EWMA volatility state with new 1-minute close.
        
        Args:
            asset: Asset symbol
            new_close: New close price
            timestamp: Timestamp of new close
        
        Returns:
            Updated VolatilityState
        """
        state = self._states.get(asset)
        
        if state is None:
            # Initialize if doesn't exist
            # Use conservative initial variance (will be bootstrapped properly later)
            initial_sigma2 = 1e-6  # Small initial variance
            return self.initialize_state(asset, initial_sigma2, new_close, timestamp)
        
        # Calculate 1-minute return
        if state.last_close_1m > 0:
            r_t = np.log(new_close / state.last_close_1m)
        else:
            r_t = 0.0  # Avoid log(0)
        
        # EWMA update
        lambda_val = state.lambda_val
        sigma2_new = lambda_val * state.sigma2_1m + (1 - lambda_val) * (r_t ** 2)
        
        # Ensure floor (avoid zero variance)
        sigma2_new = max(sigma2_new, 1e-8)
        
        # Update state
        state.sigma2_1m = sigma2_new
        state.last_close_1m = new_close
        state.last_update_ts = timestamp
        
        return state
    
    def get_sigma2_1m(self, asset: str) -> Optional[float]:
        """Get current 1-minute variance for asset."""
        state = self._states.get(asset)
        return state.sigma2_1m if state else None
    
    def get_last_close(self, asset: str) -> Optional[float]:
        """Get last close price for asset."""
        state = self._states.get(asset)
        return state.last_close_1m if state else None
    
    def get_last_update(self, asset: str) -> Optional[datetime]:
        """Get last update timestamp for asset."""
        state = self._states.get(asset)
        return state.last_update_ts if state else None
    
    def all_assets(self) -> list:
        """Get list of all assets with state."""
        return list(self._states.keys())
    
    def remove_state(self, asset: str):
        """Remove state for asset (for cleanup)."""
        if asset in self._states:
            del self._states[asset]
    
    def get_all_states(self) -> Dict[str, VolatilityState]:
        """Get all states (for persistence)."""
        return self._states.copy()


# Global instance (will be initialized per miner instance)
_volatility_manager: Optional[VolatilityStateManager] = None


def get_volatility_manager() -> VolatilityStateManager:
    """Get or create global volatility state manager."""
    global _volatility_manager
    if _volatility_manager is None:
        _volatility_manager = VolatilityStateManager()
    return _volatility_manager
