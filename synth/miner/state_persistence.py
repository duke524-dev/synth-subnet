"""
Step 7: Persist & reload state (must-have for stability).
Persists volatility state frequently and reloads on startup.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import bittensor as bt

from synth.miner.volatility_state import (
    VolatilityStateManager,
    VolatilityState,
    get_volatility_manager,
)


class StatePersistence:
    """
    Handles persistence of volatility state.
    
    State is persisted:
    - Every 1-5 minutes (configurable)
    - On graceful shutdown
    """
    
    def __init__(self, state_dir: str = "data/miner_state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_file = self.state_dir / "volatility_state.json"
        self.last_persist_time: Dict[str, datetime] = {}
        self.persist_interval = 30  # seconds (minimum between persists)
        self.force_persist_interval = 300  # 5 minutes (force persist)
    
    def persist_state(self, manager: VolatilityStateManager) -> bool:
        """
        Persist all volatility states to disk.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            states = manager.get_all_states()
            
            # Convert to JSON-serializable format
            state_dict = {}
            for asset, state in states.items():
                state_dict[asset] = {
                    "asset": state.asset,
                    "sigma2_1m": float(state.sigma2_1m),
                    "last_close_1m": float(state.last_close_1m),
                    "last_update_ts": state.last_update_ts.isoformat(),
                    "lambda_val": float(state.lambda_val),
                    "state_version": state.state_version,
                }
            
            # Write to temporary file first, then rename (atomic write)
            temp_file = self.state_file.with_suffix(".json.tmp")
            
            with open(temp_file, "w") as f:
                json.dump(state_dict, f, indent=2)
            
            # Atomic rename
            temp_file.replace(self.state_file)
            
            bt.logging.debug(f"Persisted state for {len(states)} assets")
            return True
        
        except Exception as e:
            bt.logging.error(f"Failed to persist state: {e}")
            return False
    
    def persist_if_needed(
        self,
        asset: str,
        manager: VolatilityStateManager,
        force: bool = False,
    ) -> bool:
        """
        Persist state if needed (based on time interval).
        
        Args:
            asset: Asset that triggered the check
            manager: Volatility state manager
            force: Force persist regardless of interval
        
        Returns:
            True if persisted, False otherwise
        """
        now = datetime.now(timezone.utc)
        last_persist = self.last_persist_time.get(asset)
        
        # Force persist if > 5 minutes since last persist (any asset)
        if last_persist:
            time_since_last = (now - last_persist).total_seconds()
            if time_since_last > self.force_persist_interval:
                force = True
        else:
            # Never persisted before
            force = True
        
        if force or not last_persist:
            # Check time since last persist for any asset
            if last_persist:
                time_since_last = (now - last_persist).total_seconds()
                if time_since_last < self.persist_interval and not force:
                    return False  # Too soon
            
            # Persist
            success = self.persist_state(manager)
            if success:
                self.last_persist_time[asset] = now
            return success
        
        return False
    
    def reload_state(self, manager: VolatilityStateManager) -> bool:
        """
        Reload volatility state from disk.
        
        Returns:
            True if reloaded successfully, False if file doesn't exist or error
        """
        if not self.state_file.exists():
            bt.logging.info("No saved state file found, starting fresh")
            return False
        
        try:
            with open(self.state_file, "r") as f:
                state_dict = json.load(f)
            
            # Reload each state
            loaded_count = 0
            for asset, state_data in state_dict.items():
                try:
                    state = VolatilityState(
                        asset=state_data["asset"],
                        sigma2_1m=float(state_data["sigma2_1m"]),
                        last_close_1m=float(state_data["last_close_1m"]),
                        last_update_ts=datetime.fromisoformat(
                            state_data["last_update_ts"]
                        ).replace(tzinfo=timezone.utc),
                        lambda_val=float(state_data["lambda_val"]),
                        state_version=state_data.get("state_version", 1),
                    )
                    
                    manager._states[asset] = state
                    loaded_count += 1
                
                except Exception as e:
                    bt.logging.warning(
                        f"Failed to reload state for {asset}: {e}"
                    )
                    continue
            
            if loaded_count > 0:
                bt.logging.info(f"Reloaded state for {loaded_count} assets")
                return True
            else:
                bt.logging.warning("No states successfully reloaded")
                return False
        
        except Exception as e:
            bt.logging.error(f"Failed to reload state: {e}")
            return False


# Global persistence instance
_persistence: Optional[StatePersistence] = None


def get_persistence(state_dir: Optional[str] = None) -> StatePersistence:
    """Get or create global state persistence instance."""
    global _persistence
    if _persistence is None:
        _persistence = StatePersistence(state_dir or "data/miner_state")
    return _persistence


def reload_all_states(state_dir: Optional[str] = None) -> bool:
    """Convenience function to reload all states on startup."""
    manager = get_volatility_manager()
    persistence = get_persistence(state_dir)
    return persistence.reload_state(manager)


def persist_state_if_needed(
    asset: str,
    force: bool = False,
    state_dir: Optional[str] = None,
) -> bool:
    """Convenience function to persist state if needed."""
    manager = get_volatility_manager()
    persistence = get_persistence(state_dir)
    return persistence.persist_if_needed(asset, manager, force)
