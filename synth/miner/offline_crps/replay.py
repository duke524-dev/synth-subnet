"""
Step 15: Offline CRPS replay script
Replays saved predictions through validator CRPS code.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import numpy as np
import json
from pathlib import Path
import bittensor as bt

from synth.miner.prediction_logger import PredictionLogger, get_prediction_logger
from synth.miner.offline_crps.crps_calculation import calculate_crps_for_miner
from synth.miner.offline_crps.prompt_config import LOW_FREQUENCY, HIGH_FREQUENCY
from synth.miner.offline_crps.historical_price_fetcher import (
    fetch_realized_prices,
    align_prices_to_grid,
)


class CRPSReplay:
    """
    Offline CRPS replay processor.
    
    For each saved prediction:
    1. Load price_paths (do NOT regenerate)
    2. Fetch realized prices from Pyth
    3. Align to exact grid
    4. Call copied validator CRPS code
    5. Store CRPS results + metadata
    """
    
    def __init__(
        self,
        results_dir: str = "data/crps_results",
    ):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def get_prompt_config(self, prompt_label: str):
        """Get prompt config for label."""
        if prompt_label == "low":
            return LOW_FREQUENCY
        elif prompt_label == "high":
            return HIGH_FREQUENCY
        else:
            raise ValueError(f"Unknown prompt label: {prompt_label}")
    
    def replay_prediction(
        self,
        prediction_record: Dict[str, Any],
        realized_prices: Optional[np.ndarray] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Replay a single prediction through CRPS calculation.
        
        Args:
            prediction_record: Saved prediction record
            realized_prices: Optional pre-fetched realized prices
        
        Returns:
            CRPS results dict, or None if replay failed
        """
        try:
            # Extract prediction data
            t0_str = prediction_record["t0"]
            asset = prediction_record["asset"]
            prompt_label = prediction_record["prompt"]
            time_increment = prediction_record["time_increment"]
            time_length = prediction_record["time_length"]
            price_paths = prediction_record["price_paths"]
            
            # Convert t0 to datetime
            t0 = datetime.fromisoformat(t0_str).replace(tzinfo=timezone.utc)
            
            # Convert price_paths to numpy array
            # Format: list of 1000 paths, each is list of prices
            simulation_runs = np.array(price_paths, dtype=np.float64)
            
            # Shape: (1000, steps+1)
            if simulation_runs.shape[0] != 1000:
                bt.logging.warning(
                    f"Wrong number of paths: {simulation_runs.shape[0]} != 1000"
                )
                return None
            
            # Get realized prices if not provided
            if realized_prices is None:
                realized_prices = fetch_realized_prices(
                    asset=asset,
                    start_time=t0,
                    time_length=time_length,
                    time_increment=time_increment,
                )
            
            if realized_prices is None:
                bt.logging.warning(f"Cannot fetch realized prices for {asset} at {t0}")
                return None
            
            # Ensure same length as simulation paths
            expected_length = time_length // time_increment + 1
            if len(realized_prices) != expected_length:
                bt.logging.warning(
                    f"Price length mismatch: {len(realized_prices)} != {expected_length}"
                )
                return None
            
            # Get prompt config for scoring intervals
            prompt_config = self.get_prompt_config(prompt_label)
            
            # Calculate CRPS using copied validator code
            total_crps, detailed_crps_data = calculate_crps_for_miner(
                simulation_runs=simulation_runs,
                real_price_path=realized_prices,
                time_increment=time_increment,
                scoring_intervals=prompt_config.scoring_intervals,
            )
            
            # Compile results
            crps_result = {
                "prediction_id": prediction_record.get("logged_at", t0_str),
                "t0": t0_str,
                "asset": asset,
                "prompt": prompt_label,
                "total_crps": float(total_crps),
                "detailed_crps": detailed_crps_data,
                "model_version": prediction_record.get("model_version"),
                "parameter_hash": prediction_record.get("parameter_hash"),
                "replayed_at": datetime.now(timezone.utc).isoformat(),
            }
            
            return crps_result
        
        except Exception as e:
            bt.logging.error(f"CRPS replay failed: {e}", exc_info=True)
            return None
    
    def save_crps_result(self, crps_result: Dict[str, Any]):
        """Save CRPS result to disk."""
        t0_str = crps_result["t0"]
        t0 = datetime.fromisoformat(t0_str)
        
        # Save to monthly directory
        month_dir = self.results_dir / t0.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"crps_results_{t0.strftime('%Y-%m-%d')}.jsonl"
        filepath = month_dir / filename
        
        try:
            with open(filepath, "a") as f:
                json.dump(crps_result, f)
                f.write("\n")
        except Exception as e:
            bt.logging.error(f"Failed to save CRPS result: {e}")
    
    def replay_all_predictions(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        asset: Optional[str] = None,
        prompt_label: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Replay all predictions in date range.
        
        Returns:
            List of CRPS results
        """
        logger = get_prediction_logger()
        
        # Get saved predictions
        predictions = logger.get_logged_predictions(
            start_date=start_date,
            end_date=end_date,
            asset=asset,
            prompt_label=prompt_label,
        )
        
        bt.logging.info(f"Replaying {len(predictions)} predictions...")
        
        results = []
        for i, pred in enumerate(predictions):
            if (i + 1) % 10 == 0:
                bt.logging.info(f"Replayed {i+1}/{len(predictions)} predictions...")
            
            crps_result = self.replay_prediction(pred)
            
            if crps_result:
                self.save_crps_result(crps_result)
                results.append(crps_result)
        
        bt.logging.info(f"Completed replay: {len(results)}/{len(predictions)} successful")
        
        return results
