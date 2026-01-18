"""
Step 17: Parameter governance (slow tuning)
Controls parameter tuning with strict rules and timing constraints.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
import json
from pathlib import Path
import bittensor as bt

from synth.miner.volatility_state import DEFAULT_LAMBDA
from synth.miner.volatility_scaling import SIGMA_CAP_DAILY
from synth.miner.path_generator import DEFAULT_DF


# Timing constraints
FIRST_TUNING_ELIGIBILITY_DAYS = 14  # Must wait 14 days before first tuning
MIN_TIME_BETWEEN_TUNINGS_DAYS = 30  # Minimum 30 days between tunings
POST_TUNING_OBSERVATION_DAYS = 14  # 14 days observation after tuning


class ParameterGovernance:
    """
    Manages parameter tuning with strict governance rules.
    
    Rules:
    - Do not tune for first 14 calendar days
    - After that, tune at most once per 30 days per asset
    - Change one parameter at a time
    - Small bounded steps
    """
    
    def __init__(self, state_file: str = "data/miner_state/tuning_history.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load tuning history
        self.tuning_history = self._load_history()
        self.miner_start_date = self._get_miner_start_date()
    
    def _load_history(self) -> Dict[str, Any]:
        """Load tuning history from disk."""
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            bt.logging.warning(f"Failed to load tuning history: {e}")
            return {}
    
    def _save_history(self):
        """Save tuning history to disk."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.tuning_history, f, indent=2)
        except Exception as e:
            bt.logging.error(f"Failed to save tuning history: {e}")
    
    def _get_miner_start_date(self) -> datetime:
        """Get miner start date (first tuning record or current date)."""
        if "miner_start_date" in self.tuning_history:
            return datetime.fromisoformat(self.tuning_history["miner_start_date"])
        else:
            # First run - record start date
            start_date = datetime.now()
            self.tuning_history["miner_start_date"] = start_date.isoformat()
            self._save_history()
            return start_date
    
    def is_tuning_eligible(
        self,
        asset: str,
        parameter_name: str,
    ) -> Tuple[bool, str]:
        """
        Check if parameter tuning is allowed.
        
        Rules:
        - First tuning: require 14 days since miner start
        - Subsequent tunings: require 30 days since last tune + 14 days observation
        
        Returns:
            (eligible: bool, reason: str)
        """
        now = datetime.now()
        days_since_start = (now - self.miner_start_date).days
        
        # First tuning: require 14 days
        key = f"{asset}_{parameter_name}"
        last_tune_record = self.tuning_history.get(key)
        
        if last_tune_record is None:
            if days_since_start < FIRST_TUNING_ELIGIBILITY_DAYS:
                return False, (
                    f"First tuning requires {FIRST_TUNING_ELIGIBILITY_DAYS} days "
                    f"(current: {days_since_start})"
                )
            return True, "First tuning eligible"
        
        # Subsequent tuning: check timing constraints
        last_tune_date = datetime.fromisoformat(last_tune_record["date"])
        days_since_tune = (now - last_tune_date).days
        
        # Check minimum time between tunings
        if days_since_tune < MIN_TIME_BETWEEN_TUNINGS_DAYS:
            return False, (
                f"Min {MIN_TIME_BETWEEN_TUNINGS_DAYS} days between tunings "
                f"(current: {days_since_tune})"
            )
        
        # Check observation period
        observation_end = last_tune_date + timedelta(days=POST_TUNING_OBSERVATION_DAYS)
        if now < observation_end:
            return False, (
                f"Still in {POST_TUNING_OBSERVATION_DAYS}-day observation period "
                f"(ends: {observation_end.date()})"
            )
        
        return True, "Tuning eligible"
    
    def get_current_parameter_value(
        self,
        asset: str,
        parameter_name: str,
    ) -> Optional[float]:
        """Get current parameter value (from defaults or last tuning)."""
        key = f"{asset}_{parameter_name}"
        last_tune = self.tuning_history.get(key)
        
        if last_tune:
            return last_tune["value"]
        
        # Return default
        defaults = {
            "lambda": DEFAULT_LAMBDA,
            "df": DEFAULT_DF,
            "sigma_cap_daily": SIGMA_CAP_DAILY,
        }
        
        param_defaults = defaults.get(parameter_name, {})
        return param_defaults.get(asset)
    
    def get_parameter_bounds(
        self,
        asset: str,
        parameter_name: str,
    ) -> Tuple[float, float]:
        """Get bounds for parameter changes."""
        # Conservative bounds per parameter type
        if parameter_name == "lambda":
            # Lambda: 0.8 - 0.99
            return 0.80, 0.99
        elif parameter_name == "df":
            # df: 3 - 50
            return 3.0, 50.0
        elif parameter_name == "sigma_cap_daily":
            # Daily cap: 0.01 - 0.20 (1% - 20%)
            return 0.01, 0.20
        else:
            # Unknown parameter
            return 0.0, 100.0
    
    def get_max_step_size(
        self,
        parameter_name: str,
    ) -> float:
        """Get maximum step size for parameter changes."""
        max_steps = {
            "lambda": 0.01,  # ±0.01
            "df": 1.0,  # ±1
            "sigma_cap_daily": 0.01,  # ±1% (quarterly only)
        }
        return max_steps.get(parameter_name, 0.1)
    
    def propose_parameter_change(
        self,
        asset: str,
        parameter_name: str,
        new_value: float,
        reason: str,
    ) -> Tuple[bool, str]:
        """
        Propose a parameter change (validates bounds and step size).
        
        Args:
            asset: Asset symbol
            parameter_name: Parameter name (lambda, df, sigma_cap_daily)
            new_value: Proposed new value
            reason: Reason for change (for logging)
        
        Returns:
            (success: bool, message: str)
        """
        # Check eligibility
        eligible, eligibility_reason = self.is_tuning_eligible(asset, parameter_name)
        if not eligible:
            return False, eligibility_reason
        
        # Get current value
        current_value = self.get_current_parameter_value(asset, parameter_name)
        if current_value is None:
            return False, f"Unknown parameter: {parameter_name} for {asset}"
        
        # Check bounds
        min_val, max_val = self.get_parameter_bounds(asset, parameter_name)
        if new_value < min_val or new_value > max_val:
            return False, (
                f"Value {new_value} out of bounds [{min_val}, {max_val}]"
            )
        
        # Check step size
        max_step = self.get_max_step_size(parameter_name)
        step_size = abs(new_value - current_value)
        if step_size > max_step:
            return False, (
                f"Step size {step_size:.4f} exceeds max {max_step:.4f}"
            )
        
        # Record tuning
        key = f"{asset}_{parameter_name}"
        self.tuning_history[key] = {
            "date": datetime.now().isoformat(),
            "asset": asset,
            "parameter": parameter_name,
            "old_value": current_value,
            "new_value": new_value,
            "reason": reason,
        }
        
        self._save_history()
        
        bt.logging.info(
            f"Parameter tuning recorded: {asset} {parameter_name} "
            f"{current_value} -> {new_value} ({reason})"
        )
        
        return True, f"Parameter change recorded: {current_value} -> {new_value}"
    
    def get_tuning_suggestions(
        self,
        diagnostics: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Generate tuning suggestions based on diagnostics.
        
        Mapping:
        - short-horizon CRPS bad -> lambda down
        - too many 95% breaches -> df down
        - too wide distribution -> df up
        - abs endpoints unstable -> sigma_cap down (quarterly only)
        
        Returns:
            List of tuning suggestions
        """
        suggestions = []
        
        # Analyze horizon statistics
        horizon_stats = diagnostics.get("horizon_statistics", {})
        
        # Short-horizon CRPS analysis
        short_stats = horizon_stats.get("short", {})
        if short_stats and short_stats.get("mean", 0) > 100:  # Threshold
            suggestions.append({
                "asset": "ALL",  # Apply to all if needed
                "parameter": "lambda",
                "direction": "down",
                "reason": "Short-horizon CRPS too high",
                "change": -0.01,
            })
        
        # Coverage analysis (if available)
        coverage = diagnostics.get("coverage_rates", {})
        if coverage:
            coverage_95 = coverage.get("95%", 0.95)
            if coverage_95 < 0.90:  # Too many breaches
                suggestions.append({
                    "asset": "ALL",
                    "parameter": "df",
                    "direction": "down",
                    "reason": "95% coverage too low (too many breaches)",
                    "change": -1,
                })
            elif coverage_95 > 0.98:  # Too conservative
                suggestions.append({
                    "asset": "ALL",
                    "parameter": "df",
                    "direction": "up",
                    "reason": "95% coverage too high (too conservative)",
                    "change": +1,
                })
        
        return suggestions


# Global instance
_governance: Optional[ParameterGovernance] = None


def get_governance() -> ParameterGovernance:
    """Get or create global parameter governance instance."""
    global _governance
    if _governance is None:
        _governance = ParameterGovernance()
    return _governance
