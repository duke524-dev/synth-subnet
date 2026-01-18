"""
Step 13: Prediction logging (disk-efficient)
Saves predictions with sampling strategy for offline CRPS tuning.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import json
import hashlib
import os
from pathlib import Path
import bittensor as bt

from synth.simulation_input import SimulationInput


class PredictionLogger:
    """
    Logs predictions with sampling strategy.
    
    Sampling rules:
    - LOW: every 30 minutes
    - HIGH: every 15 minutes
    - Volatility spikes (rate-limited)
    - Equity open/close windows
    """
    
    def __init__(
        self,
        storage_dir: str = "data/predictions",
        model_version: str = "v1.0.0",
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.model_version = model_version
        
        # Sampling state tracking
        self.last_logged_time = {}  # (asset, prompt_label) -> datetime
        self.volatility_spike_logged = {}  # Rate limiting for spikes
        
        # Prompt labels
        self.PROMPT_LOW = "low"
        self.PROMPT_HIGH = "high"
        
        # Sampling intervals (seconds)
        self.LOW_INTERVAL = 30 * 60   # 30 minutes
        self.HIGH_INTERVAL = 15 * 60  # 15 minutes
    
    def _get_parameter_hash(self, config: Dict[str, Any]) -> str:
        """Generate hash of current parameters for tracking."""
        # Hash relevant parameters that affect predictions
        param_dict = {
            'lambda': config.get('lambda'),
            'df': config.get('df'),
            'sigma_cap_daily': config.get('sigma_cap_daily'),
            'shrink_high': config.get('shrink_high'),
        }
        param_str = json.dumps(param_dict, sort_keys=True)
        return hashlib.sha256(param_str.encode()).hexdigest()[:16]
    
    def _get_prompt_label(
        self,
        time_increment: int,
        time_length: int
    ) -> str:
        """Determine prompt label from timing parameters."""
        # LOW: 300s increment, 86400s length
        # HIGH: 60s increment, 3600s length
        if time_increment == 300 and time_length == 86400:
            return self.PROMPT_LOW
        elif time_increment == 60 and time_length == 3600:
            return self.PROMPT_HIGH
        else:
            return "unknown"
    
    def _should_log(
        self,
        asset: str,
        prompt_label: str,
        current_time: datetime,
        volatility_spike: bool = False,
        equity_market_event: bool = False,
    ) -> bool:
        """
        Determine if prediction should be logged based on sampling strategy.
        
        Returns:
            True if should log, False otherwise
        """
        key = (asset, prompt_label)
        last_logged = self.last_logged_time.get(key)
        
        # Always log if no previous log
        if last_logged is None:
            return True
        
        # Check interval-based sampling
        interval = self.LOW_INTERVAL if prompt_label == self.PROMPT_LOW else self.HIGH_INTERVAL
        time_since_last = (current_time - last_logged).total_seconds()
        
        if time_since_last >= interval:
            return True
        
        # Check volatility spike (rate-limited: max once per hour)
        if volatility_spike:
            spike_key = (asset, prompt_label, current_time.hour)
            if spike_key not in self.volatility_spike_logged:
                self.volatility_spike_logged[spike_key] = current_time
                return True
        
        # Check equity market events
        if equity_market_event:
            return True
        
        return False
    
    def _get_storage_path(self, timestamp: datetime) -> Path:
        """Get storage path for a given timestamp."""
        month_dir = self.storage_dir / timestamp.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"predictions_{timestamp.strftime('%Y-%m-%d')}.jsonl"
        return month_dir / filename
    
    def log_prediction(
        self,
        simulation_input: SimulationInput,
        price_paths: List[List[float]],
        config: Dict[str, Any],
        request_time: datetime,
        volatility_spike: bool = False,
        equity_market_event: bool = False,
    ) -> Optional[str]:
        """
        Log prediction if sampling strategy allows.
        
        Args:
            simulation_input: Request parameters
            price_paths: List of 1000 price paths
            config: Current model configuration
            request_time: When request was received
            volatility_spike: Whether volatility spike detected
            equity_market_event: Whether equity market event (open/close)
        
        Returns:
            File path if logged, None if skipped
        """
        asset = simulation_input.asset
        prompt_label = self._get_prompt_label(
            simulation_input.time_increment,
            simulation_input.time_length
        )
        
        # Check if should log
        if not self._should_log(
            asset=asset,
            prompt_label=prompt_label,
            current_time=request_time,
            volatility_spike=volatility_spike,
            equity_market_event=equity_market_event,
        ):
            return None
        
        # Prepare metadata
        start_time_dt = datetime.fromisoformat(simulation_input.start_time)
        parameter_hash = self._get_parameter_hash(config)
        
        prediction_record = {
            # Request metadata
            "t0": simulation_input.start_time,
            "request_time": request_time.isoformat(),
            "asset": asset,
            "prompt": prompt_label,
            "time_increment": simulation_input.time_increment,
            "time_length": simulation_input.time_length,
            "num_simulations": simulation_input.num_simulations,
            
            # Model metadata
            "model_version": self.model_version,
            "parameter_hash": parameter_hash,
            "config_snapshot": config,  # Full config for reference
            
            # Calculation metadata
            "steps": simulation_input.time_length // simulation_input.time_increment,
            "horizon_hours": simulation_input.time_length / 3600,
            
            # Logging metadata
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "log_reason": (
                "interval" if not volatility_spike and not equity_market_event
                else ("volatility_spike" if volatility_spike else "market_event")
            ),
            
            # Prediction data
            "price_paths": price_paths,  # Full 1000 paths
        }
        
        # Write to JSONL file
        storage_path = self._get_storage_path(start_time_dt)
        
        try:
            with open(storage_path, "a") as f:
                json.dump(prediction_record, f)
                f.write("\n")
            
            # Update last logged time
            self.last_logged_time[(asset, prompt_label)] = request_time
            
            bt.logging.debug(
                f"Logged prediction: asset={asset}, prompt={prompt_label}, "
                f"path={storage_path}"
            )
            
            return str(storage_path)
        
        except Exception as e:
            bt.logging.error(f"Failed to log prediction: {e}")
            return None
    
    def get_logged_predictions(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        asset: Optional[str] = None,
        prompt_label: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve logged predictions for offline analysis.
        
        Returns:
            List of prediction records
        """
        predictions = []
        
        # Determine date range
        if start_date is None:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        if end_date is None:
            end_date = datetime.now(timezone.utc)
        
        # Iterate through date range
        current_date = start_date.replace(day=1)  # Start of month
        while current_date <= end_date:
            month_dir = self.storage_dir / current_date.strftime("%Y-%m")
            
            if month_dir.exists():
                # Read all JSONL files in month
                for jsonl_file in month_dir.glob("predictions_*.jsonl"):
                    try:
                        with open(jsonl_file, "r") as f:
                            for line in f:
                                record = json.loads(line)
                                record_date = datetime.fromisoformat(record["t0"])
                                
                                # Apply filters
                                if record_date < start_date or record_date > end_date:
                                    continue
                                if asset and record["asset"] != asset:
                                    continue
                                if prompt_label and record["prompt"] != prompt_label:
                                    continue
                                
                                predictions.append(record)
                    except Exception as e:
                        bt.logging.warning(f"Error reading {jsonl_file}: {e}")
            
            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)
        
        return predictions


# Global logger instance
_prediction_logger: Optional[PredictionLogger] = None


def get_prediction_logger(
    storage_dir: Optional[str] = None,
    model_version: Optional[str] = None,
) -> PredictionLogger:
    """Get or create global prediction logger."""
    global _prediction_logger
    if _prediction_logger is None:
        _prediction_logger = PredictionLogger(
            storage_dir=storage_dir or "data/predictions",
            model_version=model_version or "v1.0.0",
        )
    return _prediction_logger
