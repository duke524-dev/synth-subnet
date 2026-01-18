"""
Automated offline CRPS replay and parameter tuning.
Runs periodically in background to analyze performance and suggest tuning.
"""

import asyncio
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import bittensor as bt

from synth.miner.offline_crps.replay import CRPSReplay
from synth.miner.offline_crps.diagnostics import (
    generate_diagnostics_report,
    print_diagnostics_report,
)
from synth.miner.parameter_governance import get_governance, ParameterGovernance


class AutomatedTuningScheduler:
    """
    Automated scheduler for offline CRPS replay and parameter tuning.
    
    Runs tasks periodically:
    - CRPS Replay: Daily (at configurable hour)
    - Diagnostics Review: Weekly
    - Parameter Tuning Check: Weekly (if eligible)
    """
    
    def __init__(
        self,
        crps_replay_interval_hours: int = 24,
        diagnostics_interval_hours: int = 168,  # Weekly
        tuning_check_interval_hours: int = 168,  # Weekly
        crps_replay_days: int = 7,
        enabled: bool = True,
        # Configurable thresholds
        good_crps_threshold: float = 50.0,
        high_short_crps_threshold: float = 100.0,
        high_long_crps_threshold: float = 200.0,
        coverage_low_threshold: float = 0.93,
        coverage_high_threshold: float = 0.97,
        min_data_points: int = 10,
    ):
        self.crps_replay_interval_hours = crps_replay_interval_hours
        self.diagnostics_interval_hours = diagnostics_interval_hours
        self.tuning_check_interval_hours = tuning_check_interval_hours
        self.crps_replay_days = crps_replay_days
        self.enabled = enabled
        
        # Store thresholds
        self.good_crps_threshold = good_crps_threshold
        self.high_short_crps_threshold = high_short_crps_threshold
        self.high_long_crps_threshold = high_long_crps_threshold
        self.coverage_low_threshold = coverage_low_threshold
        self.coverage_high_threshold = coverage_high_threshold
        self.min_data_points = min_data_points
        
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        # Track last run times
        self.last_crps_replay: Optional[datetime] = None
        self.last_diagnostics: Optional[datetime] = None
        self.last_tuning_check: Optional[datetime] = None
        
        # Components
        self.replay = CRPSReplay()
        self.governance = get_governance()
    
    def start(self):
        """Start the automated tuning scheduler in background thread."""
        if not self.enabled:
            bt.logging.info("Automated tuning scheduler disabled")
            return
        
        if self.running:
            bt.logging.warning("Automated tuning scheduler already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        bt.logging.info(
            f"Automated tuning scheduler started (CRPS replay: {self.crps_replay_interval_hours}h, "
            f"Diagnostics: {self.diagnostics_interval_hours}h, Tuning: {self.tuning_check_interval_hours}h)"
        )
    
    def stop(self):
        """Stop the automated tuning scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        bt.logging.info("Automated tuning scheduler stopped")
    
    def _run_loop(self):
        """Main loop for automated tasks."""
        while self.running:
            try:
                now = datetime.now(timezone.utc)
                
                # Check CRPS replay (daily)
                if (
                    self.last_crps_replay is None or
                    (now - self.last_crps_replay).total_seconds() >= self.crps_replay_interval_hours * 3600
                ):
                    self._run_crps_replay()
                    self.last_crps_replay = now
                
                # Check diagnostics (weekly)
                if (
                    self.last_diagnostics is None or
                    (now - self.last_diagnostics).total_seconds() >= self.diagnostics_interval_hours * 3600
                ):
                    self._run_diagnostics()
                    self.last_diagnostics = now
                
                # Check parameter tuning eligibility (weekly)
                if (
                    self.last_tuning_check is None or
                    (now - self.last_tuning_check).total_seconds() >= self.tuning_check_interval_hours * 3600
                ):
                    self._check_tuning_eligibility()
                    self.last_tuning_check = now
                
                # Sleep for 1 hour before checking again
                time.sleep(3600)
            
            except Exception as e:
                bt.logging.error(f"Error in automated tuning scheduler: {e}", exc_info=True)
                time.sleep(3600)  # Sleep before retrying
    
    def _run_crps_replay(self):
        """Run CRPS replay on recent predictions."""
        try:
            bt.logging.info("Running automated CRPS replay...")
            
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=self.crps_replay_days)
            
            results = self.replay.replay_all_predictions(
                start_date=start_date,
                end_date=end_date,
            )
            
            bt.logging.info(f"Automated CRPS replay completed: {len(results)} predictions replayed")
        
        except Exception as e:
            bt.logging.error(f"Automated CRPS replay failed: {e}", exc_info=True)
    
    def _run_diagnostics(self):
        """Generate and review diagnostics."""
        try:
            bt.logging.info("Running automated diagnostics...")
            
            # Load recent CRPS results
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=self.crps_replay_days)
            
            # Get CRPS results from files
            results = []
            results_dir = self.replay.results_dir
            current_date = start_date.replace(day=1)
            
            while current_date <= end_date:
                month_dir = results_dir / current_date.strftime("%Y-%m")
                if month_dir.exists():
                    import json
                    for jsonl_file in month_dir.glob("crps_results_*.jsonl"):
                        try:
                            with open(jsonl_file, "r") as f:
                                for line in f:
                                    result = json.loads(line)
                                    result_date = datetime.fromisoformat(result["t0"])
                                    if start_date <= result_date <= end_date:
                                        results.append(result)
                        except Exception as e:
                            bt.logging.warning(f"Error reading {jsonl_file}: {e}")
                
                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
            
            if results:
                report = generate_diagnostics_report(results)
                
                # Print summary with status
                bt.logging.info("Automated Diagnostics Summary:")
                
                overall_stats = report.get("overall_statistics")
                if overall_stats:
                    mean_crps = overall_stats.get("mean_crps", 0)
                    count = overall_stats.get("count", 0)
                    
                    # Determine performance status
                    if mean_crps < self.good_crps_threshold:
                        status = "✅ GOOD"
                    elif mean_crps < self.high_short_crps_threshold:
                        status = "⚠️  ACCEPTABLE"
                    else:
                        status = "❌ NEEDS IMPROVEMENT"
                    
                    bt.logging.info(
                        f"  Mean CRPS: {mean_crps:.4f} ({status}, threshold: {self.good_crps_threshold}), "
                        f"Count: {count}"
                    )
                
                if report.get("horizon_statistics"):
                    bt.logging.info("  CRPS by Horizon:")
                    for horizon, stats in report["horizon_statistics"].items():
                        bt.logging.info(
                            f"    {horizon}: mean={stats['mean']:.4f}, count={stats['count']}"
                        )
                
                # Get tuning suggestions with configurable thresholds
                suggestions = self.governance.get_tuning_suggestions(
                    report,
                    good_crps_threshold=self.good_crps_threshold,
                    high_short_crps_threshold=self.high_short_crps_threshold,
                    high_long_crps_threshold=self.high_long_crps_threshold,
                    coverage_low_threshold=self.coverage_low_threshold,
                    coverage_high_threshold=self.coverage_high_threshold,
                    min_data_points=self.min_data_points,
                )
                
                if not suggestions:
                    bt.logging.info("  ✅ Performance is good - no parameter tuning suggested")
                else:
                    bt.logging.warning(f"  ⚠️  Tuning suggestions: {len(suggestions)} found")
                    for sug in suggestions[:3]:  # Show first 3
                        bt.logging.warning(f"    - {sug}")
            else:
                bt.logging.info("No CRPS results found for diagnostics")
        
        except Exception as e:
            bt.logging.error(f"Automated diagnostics failed: {e}", exc_info=True)
    
    def _check_tuning_eligibility(self):
        """Check parameter tuning eligibility and log status."""
        try:
            bt.logging.info("Checking parameter tuning eligibility...")
            
            assets = ["BTC", "ETH", "SOL", "XAU"]
            parameters = ["lambda", "df", "sigma_cap_daily"]
            
            eligible_count = 0
            for asset in assets:
                for param in parameters:
                    eligible, reason = self.governance.is_tuning_eligible(asset, param)
                    if eligible:
                        current_value = self.governance.get_current_parameter_value(asset, param)
                        min_val, max_val = self.governance.get_parameter_bounds(asset, param)
                        max_step = self.governance.get_max_step_size(param)
                        
                        bt.logging.info(
                            f"  ✅ {asset}/{param}: eligible (current={current_value:.4f}, "
                            f"bounds=[{min_val:.4f}, {max_val:.4f}], max_step=±{max_step:.4f})"
                        )
                        eligible_count += 1
            
            if eligible_count == 0:
                bt.logging.info("  No parameters eligible for tuning at this time")
            else:
                bt.logging.info(f"  {eligible_count} parameter(s) eligible for tuning")
        
        except Exception as e:
            bt.logging.error(f"Parameter tuning eligibility check failed: {e}", exc_info=True)


# Global scheduler instance
_scheduler: Optional[AutomatedTuningScheduler] = None


def get_scheduler(
    crps_replay_interval_hours: int = 24,
    diagnostics_interval_hours: int = 168,
    tuning_check_interval_hours: int = 168,
    crps_replay_days: int = 7,
    enabled: bool = True,
    good_crps_threshold: float = 50.0,
    high_short_crps_threshold: float = 100.0,
    high_long_crps_threshold: float = 200.0,
    coverage_low_threshold: float = 0.93,
    coverage_high_threshold: float = 0.97,
    min_data_points: int = 10,
) -> AutomatedTuningScheduler:
    """Get or create global automated tuning scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AutomatedTuningScheduler(
            crps_replay_interval_hours=crps_replay_interval_hours,
            diagnostics_interval_hours=diagnostics_interval_hours,
            tuning_check_interval_hours=tuning_check_interval_hours,
            crps_replay_days=crps_replay_days,
            enabled=enabled,
            good_crps_threshold=good_crps_threshold,
            high_short_crps_threshold=high_short_crps_threshold,
            high_long_crps_threshold=high_long_crps_threshold,
            coverage_low_threshold=coverage_low_threshold,
            coverage_high_threshold=coverage_high_threshold,
            min_data_points=min_data_points,
        )
    return _scheduler
