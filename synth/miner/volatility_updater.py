"""
Background task for updating EWMA volatility state with 1-minute closes.
This provides more accurate volatility estimates than request-triggered updates.

Optional: Enable this for more accurate 1-minute volatility tracking.
Set ENABLE_BACKGROUND_UPDATER = True in neurons/miner.py to use.
"""

import asyncio
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional
import bittensor as bt

from synth.miner.volatility_state import get_volatility_manager
from synth.miner.price_fetcher import fetch_start_price


class VolatilityUpdater:
    """
    Background task that fetches 1-minute closes and updates EWMA state.
    Runs independently of validator requests for more accurate volatility tracking.
    """
    
    def __init__(self, update_interval_seconds: int = 60):
        """
        Args:
            update_interval_seconds: How often to fetch and update (default: 60s = 1 minute)
        """
        self.update_interval = update_interval_seconds
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.assets = ["BTC", "ETH", "SOL", "XAU"]  # Add more as needed
    
    def start(self):
        """Start the background updater thread."""
        if self.running:
            bt.logging.warning("VolatilityUpdater already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        bt.logging.info(f"VolatilityUpdater started (interval={self.update_interval}s)")
    
    def stop(self):
        """Stop the background updater thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
        bt.logging.info("VolatilityUpdater stopped")
    
    def _run_loop(self):
        """Main update loop."""
        import time
        
        while self.running:
            try:
                current_time = datetime.now(timezone.utc)
                manager = get_volatility_manager()
                
                for asset in self.assets:
                    try:
                        # Fetch current price (as proxy for 1-minute close)
                        price = fetch_start_price(asset, current_time)
                        
                        if price is None or price <= 0:
                            bt.logging.warning(
                                f"Failed to fetch price for {asset}, skipping update"
                            )
                            continue
                        
                        # Update volatility state
                        manager.update_state(asset, price, current_time)
                        
                    except Exception as e:
                        bt.logging.error(
                            f"Error updating volatility for {asset}: {e}",
                            exc_info=True
                        )
                
                # Sleep until next update
                time.sleep(self.update_interval)
                
            except Exception as e:
                bt.logging.error(f"Error in volatility updater loop: {e}", exc_info=True)
                time.sleep(self.update_interval)  # Continue even on error


# Global instance
_volatility_updater: Optional[VolatilityUpdater] = None


def get_volatility_updater(
    update_interval_seconds: int = 60
) -> VolatilityUpdater:
    """Get or create global volatility updater."""
    global _volatility_updater
    if _volatility_updater is None:
        _volatility_updater = VolatilityUpdater(update_interval_seconds)
    return _volatility_updater
