"""
Step 5: EWMA volatility state (the real "model")
Maintains per-asset volatility state using Exponential Weighted Moving Average.
"""

from datetime import datetime, timezone
from typing import Dict, Optional, Any
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
        """Get lambda (decay parameter) for asset, checking tuning history first."""
        # Check if parameter was tuned (from governance)
        from synth.miner.parameter_governance import get_governance
        governance = get_governance()
        tuned_value = governance.get_current_parameter_value(asset, "lambda")
        
        # If tuned value exists, use it; otherwise use default
        if tuned_value is not None:
            return tuned_value
        
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
        
        Handles irregular update intervals by scaling returns to 1-minute equivalents.
        This ensures accurate volatility estimates even when updates don't occur
        exactly every minute.
        
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
        
        # Calculate time elapsed since last update
        time_elapsed = (timestamp - state.last_update_ts).total_seconds()
        minutes_elapsed = time_elapsed / 60.0
        
        # Skip if less than 30 seconds (avoid over-updating on rapid requests)
        if minutes_elapsed < 0.5:
            bt.logging.debug(
                f"Skipping update for {asset}: only {time_elapsed:.1f}s elapsed "
                f"(need at least 30s)"
            )
            return state
        
        # Calculate total return over the elapsed period
        if state.last_close_1m > 0:
            r_total = np.log(new_close / state.last_close_1m)
        else:
            r_total = 0.0  # Avoid log(0)
        
        # Scale return to 1-minute equivalent
        # If multiple minutes elapsed, we need to scale the return
        # For EWMA, we assume constant volatility, so:
        # r_1min = r_total / sqrt(minutes_elapsed)
        # This accounts for the fact that variance scales with time
        if minutes_elapsed > 0.5:
            r_t = r_total / np.sqrt(minutes_elapsed)
        else:
            r_t = r_total  # Use raw return if very short interval
        
        # EWMA update (assumes 1-minute intervals)
        # Note: This is an approximation when minutes_elapsed != 1.0
        # For exact EWMA with irregular intervals, we'd need to adjust lambda,
        # but this approximation is reasonable for small deviations
        lambda_val = state.lambda_val
        
        # If more than 1 minute elapsed, we could apply the update multiple times
        # or use an adjusted decay factor. For simplicity, we apply once with
        # the scaled return, which is a reasonable approximation.
        sigma2_new = lambda_val * state.sigma2_1m + (1 - lambda_val) * (r_t ** 2)
        
        # Ensure floor (avoid zero variance)
        sigma2_new = max(sigma2_new, 1e-8)
        
        # Update state
        state.sigma2_1m = sigma2_new
        state.last_close_1m = new_close
        state.last_update_ts = timestamp
        
        bt.logging.debug(
            f"Updated {asset} volatility: sigma2_1m={sigma2_new:.2e}, "
            f"minutes_elapsed={minutes_elapsed:.2f}, r_t={r_t:.6f}"
        )
        
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
    
    def compare_with_persisted_state(
        self,
        state_file: str = "data/miner_state/volatility_state.json",
        threshold_pct: float = 1.0,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compare current volatility state with persisted state from disk.
        Detects parameter changes and returns detailed comparison.
        
        Args:
            state_file: Path to persisted state JSON file
            threshold_pct: Minimum percentage change to report (default: 1.0%)
        
        Returns:
            Dictionary mapping asset -> change information:
            {
                "BTC": {
                    "sigma2_1m": {
                        "changed": True,
                        "old_value": 5e-6,
                        "new_value": 6e-6,
                        "change_pct": 20.0,
                        "change_abs": 1e-6
                    },
                    "lambda_val": {
                        "changed": False,
                        "old_value": 0.94,
                        "new_value": 0.94,
                        "change_pct": 0.0,
                        "change_abs": 0.0
                    },
                    "last_close_1m": {...},
                    "last_update_ts": {...}
                },
                ...
            }
        """
        from pathlib import Path
        import json
        
        state_path = Path(state_file)
        changes = {}
        
        # Check if persisted state exists
        if not state_path.exists():
            bt.logging.debug(f"Persisted state file not found: {state_file}")
            return changes
        
        try:
            # Load persisted state
            with open(state_path, "r") as f:
                persisted_data = json.load(f)
            
            # Compare each asset
            for asset, current_state in self._states.items():
                if asset not in persisted_data:
                    # New asset, not in persisted state
                    changes[asset] = {
                        "status": "new_asset",
                        "message": f"Asset {asset} not found in persisted state"
                    }
                    continue
                
                persisted_state = persisted_data[asset]
                asset_changes = {}
                
                # Compare sigma2_1m
                old_sigma2 = float(persisted_state.get("sigma2_1m", 0))
                new_sigma2 = current_state.sigma2_1m
                if old_sigma2 > 0:
                    sigma2_change_pct = abs((new_sigma2 - old_sigma2) / old_sigma2) * 100
                    sigma2_change_abs = abs(new_sigma2 - old_sigma2)
                else:
                    sigma2_change_pct = 100.0 if new_sigma2 != 0 else 0.0
                    sigma2_change_abs = abs(new_sigma2 - old_sigma2)
                
                asset_changes["sigma2_1m"] = {
                    "changed": sigma2_change_pct >= threshold_pct,
                    "old_value": old_sigma2,
                    "new_value": new_sigma2,
                    "change_pct": sigma2_change_pct,
                    "change_abs": sigma2_change_abs,
                }
                
                # Compare lambda_val
                old_lambda = float(persisted_state.get("lambda_val", 0))
                new_lambda = current_state.lambda_val
                lambda_change_abs = abs(new_lambda - old_lambda)
                lambda_change_pct = abs((new_lambda - old_lambda) / old_lambda) * 100 if old_lambda != 0 else 0.0
                
                asset_changes["lambda_val"] = {
                    "changed": lambda_change_abs > 1e-6,  # Any change in lambda is significant
                    "old_value": old_lambda,
                    "new_value": new_lambda,
                    "change_pct": lambda_change_pct,
                    "change_abs": lambda_change_abs,
                }
                
                # Compare last_close_1m
                old_close = float(persisted_state.get("last_close_1m", 0))
                new_close = current_state.last_close_1m
                if old_close > 0:
                    close_change_pct = abs((new_close - old_close) / old_close) * 100
                else:
                    close_change_pct = 100.0 if new_close != 0 else 0.0
                
                asset_changes["last_close_1m"] = {
                    "changed": close_change_pct >= threshold_pct,
                    "old_value": old_close,
                    "new_value": new_close,
                    "change_pct": close_change_pct,
                    "change_abs": abs(new_close - old_close),
                }
                
                # Compare last_update_ts
                try:
                    old_ts_str = persisted_state.get("last_update_ts", "")
                    if old_ts_str:
                        old_ts = datetime.fromisoformat(old_ts_str.replace("Z", "+00:00"))
                        new_ts = current_state.last_update_ts
                        ts_diff_seconds = (new_ts - old_ts).total_seconds()
                        
                        asset_changes["last_update_ts"] = {
                            "changed": ts_diff_seconds > 0,
                            "old_value": old_ts_str,
                            "new_value": new_ts.isoformat(),
                            "time_diff_seconds": ts_diff_seconds,
                        }
                    else:
                        asset_changes["last_update_ts"] = {
                            "changed": True,
                            "old_value": None,
                            "new_value": current_state.last_update_ts.isoformat(),
                            "time_diff_seconds": None,
                        }
                except Exception as e:
                    bt.logging.warning(f"Error comparing timestamps for {asset}: {e}")
                    asset_changes["last_update_ts"] = {
                        "changed": True,
                        "old_value": persisted_state.get("last_update_ts", "unknown"),
                        "new_value": current_state.last_update_ts.isoformat(),
                        "time_diff_seconds": None,
                    }
                
                # Check if any significant changes occurred
                significant_changes = [
                    k for k, v in asset_changes.items()
                    if v.get("changed", False) and k != "last_update_ts"
                ]
                
                if significant_changes:
                    asset_changes["_summary"] = {
                        "has_changes": True,
                        "changed_parameters": significant_changes,
                    }
                else:
                    asset_changes["_summary"] = {
                        "has_changes": False,
                        "changed_parameters": [],
                    }
                
                changes[asset] = asset_changes
            
            # Check for assets in persisted state but not in current state
            for asset in persisted_data:
                if asset not in self._states:
                    changes[asset] = {
                        "status": "removed_asset",
                        "message": f"Asset {asset} exists in persisted state but not in current state"
                    }
            
            return changes
        
        except Exception as e:
            bt.logging.error(f"Error comparing with persisted state: {e}", exc_info=True)
            return {}


# Global instance (will be initialized per miner instance)
_volatility_manager: Optional[VolatilityStateManager] = None


def get_volatility_manager() -> VolatilityStateManager:
    """Get or create global volatility state manager."""
    global _volatility_manager
    if _volatility_manager is None:
        _volatility_manager = VolatilityStateManager()
    return _volatility_manager


def compare_state_with_persisted(
    asset: Optional[str] = None,
    state_file: str = "data/miner_state/volatility_state.json",
    threshold_pct: float = 1.0,
    log_changes: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """
    Convenience function to compare current state with persisted state.
    
    Args:
        asset: Specific asset to check (None = check all assets)
        state_file: Path to persisted state JSON file
        threshold_pct: Minimum percentage change to report
        log_changes: Whether to log detected changes
    
    Returns:
        Dictionary of changes (same format as compare_with_persisted_state)
    
    Example:
        # Check all assets
        changes = compare_state_with_persisted()
        
        # Check specific asset
        btc_changes = compare_state_with_persisted(asset="BTC")
        
        # Check with custom threshold
        changes = compare_state_with_persisted(threshold_pct=5.0)
    """
    manager = get_volatility_manager()
    all_changes = manager.compare_with_persisted_state(state_file, threshold_pct)
    
    if asset:
        # Return only requested asset
        return {asset: all_changes.get(asset, {})}
    
    # Log significant changes if requested
    if log_changes:
        for asset_name, asset_changes in all_changes.items():
            if isinstance(asset_changes, dict) and asset_changes.get("_summary", {}).get("has_changes"):
                summary = asset_changes["_summary"]
                changed_params = summary.get("changed_parameters", [])
                
                if changed_params:
                    bt.logging.info(
                        f"Parameter changes detected for {asset_name}: "
                        f"{', '.join(changed_params)}"
                    )
                    
                    # Log details for each changed parameter
                    for param in changed_params:
                        if param in asset_changes:
                            change_info = asset_changes[param]
                            if change_info.get("changed"):
                                bt.logging.info(
                                    f"  {param}: {change_info['old_value']:.6e} -> "
                                    f"{change_info['new_value']:.6e} "
                                    f"({change_info['change_pct']:.2f}% change)"
                                )
    
    return all_changes
