# Offline Tuning Features Summary (Steps 13-17)

## ✅ Completed Implementation

### Step 13: Prediction Logging
**File**: `synth/miner/prediction_logger.py`

- **Sampling Strategy**:
  - LOW frequency: Every 30 minutes
  - HIGH frequency: Every 15 minutes
  - Volatility spikes (rate-limited)
  - Equity open/close windows

- **Storage Format**: JSONL (one prediction per line)
- **Location**: `data/predictions/YYYY-MM/predictions_YYYY-MM-DD.jsonl`

- **Stored Data**:
  - Full 1000 price paths
  - Request metadata (t0, asset, prompt, parameters)
  - Model version + parameter hash
  - Timestamps

### Step 14: Validator CRPS Code (Verbatim Copy)
**Files**: `synth/miner/offline_crps/`

- **`crps_calculation.py`**: Exact copy of validator CRPS logic
- **`prompt_config.py`**: Exact copy of prompt configurations
- **Header**: "DO NOT MODIFY" warning

### Step 15: Offline CRPS Replay
**File**: `synth/miner/offline_crps/replay.py`

- **`CRPSReplay` class**: Processes saved predictions
- **Workflow**:
  1. Load saved price_paths (do NOT regenerate)
  2. Fetch realized prices from Pyth (historical)
  3. Align to exact grid (t0 + k*increment)
  4. Call copied validator CRPS code
  5. Store CRPS results + metadata

- **Results Location**: `data/crps_results/YYYY-MM/crps_results_YYYY-MM-DD.jsonl`

### Step 16: Diagnostics
**File**: `synth/miner/offline_crps/diagnostics.py`

- **Coverage Rates**: 5% / 50% / 95% coverage analysis
- **CRPS by Horizon**:
  - Short: 1-5min intervals
  - Medium: 15-60min intervals
  - Long: 3h / abs intervals
- **Rolling Averages**: By asset, 7-day rolling windows
- **Overall Statistics**: Mean, median, std, min, max

### Step 17: Parameter Governance
**File**: `synth/miner/parameter_governance.py`

- **Timing Constraints**:
  - First tuning: ≥14 calendar days
  - Between tunings: ≥30 calendar days
  - Observation period: 14 days after tuning

- **Change Rules**:
  - One parameter per asset at a time
  - Bounded steps:
    - lambda: ±0.01
    - df: ±1
    - sigma_cap_daily: ±1% (quarterly only)

- **Tuning Suggestions**:
  - Short-horizon CRPS bad → lambda down
  - 95% misses too often → df down
  - Too conservative → df up
  - Abs endpoints unstable → sigma_cap down (quarterly)

## Usage

### Logging Predictions (Automatic)
Predictions are automatically logged by the request handler using sampling strategy.

### Running Offline CRPS Replay

```python
from synth.miner.offline_crps.replay import CRPSReplay
from datetime import datetime, timedelta

replay = CRPSReplay()

# Replay all predictions from last 30 days
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

results = replay.replay_all_predictions(
    start_date=start_date,
    end_date=end_date,
    asset="BTC",  # Optional: filter by asset
    prompt_label="low",  # Optional: filter by prompt
)
```

### Generating Diagnostics

```python
from synth.miner.offline_crps.diagnostics import (
    generate_diagnostics_report,
    print_diagnostics_report,
)

# Generate report
report = generate_diagnostics_report(crps_results)

# Print report
print_diagnostics_report(report)
```

### Parameter Tuning

```python
from synth.miner.parameter_governance import get_governance

governance = get_governance()

# Check eligibility
eligible, reason = governance.is_tuning_eligible("BTC", "lambda")
if eligible:
    # Propose change
    success, msg = governance.propose_parameter_change(
        asset="BTC",
        parameter_name="lambda",
        new_value=0.93,  # Current: 0.94
        reason="Short-horizon CRPS too high",
    )
```

## Workflow

1. **Live Mining**: Predictions logged automatically (sampling)
2. **Daily/Weekly**: Run offline CRPS replay on saved predictions
3. **Monthly**: Review diagnostics, decide on parameter tuning
4. **Tuning**: Use governance to propose changes (if eligible)
5. **Observation**: Wait 14 days, then repeat

## Data Flow

```
Request → Generate Paths → Validate → Response
                              ↓
                         Log Prediction (sampled)
                              ↓
                    [Saved to JSONL file]
                              ↓
                    [After time passes...]
                              ↓
                    Fetch Realized Prices
                              ↓
                    Calculate CRPS (validator code)
                              ↓
                    [Save CRPS results]
                              ↓
                    Generate Diagnostics
                              ↓
                    Parameter Governance (if eligible)
```

## Key Principles

1. **Never modify validator CRPS code** - Exact copy only
2. **Don't regenerate paths** - Use saved predictions for replay
3. **Governance is strict** - Timing and bounds enforced
4. **One parameter at a time** - Controlled, incremental changes
5. **Monthly cadence** - Slow, deliberate tuning
