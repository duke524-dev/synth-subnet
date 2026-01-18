# Offline CRPS Tuning - Usage Guide

## Overview

The offline tuning system allows you to:
1. **Replay predictions** through validator CRPS code
2. **Generate diagnostics** (coverage, CRPS by horizon)
3. **Tune parameters** with governance (timing, bounds)

## Quick Start

### 1. Run CRPS Replay

Replay predictions from the last 30 days:

```bash
python3 scripts/offline_crps_replay.py --days 30
```

Replay specific asset/prompt:

```bash
python3 scripts/offline_crps_replay.py --days 30 --asset BTC --prompt low
```

Replay specific date range:

```bash
python3 scripts/offline_crps_replay.py \
    --start-date 2025-01-01 \
    --end-date 2025-01-31 \
    --asset BTC
```

### 2. Generate Diagnostics Only

If you've already run replay, generate diagnostics from existing results:

```bash
python3 scripts/offline_crps_replay.py --diagnostics-only --days 30
```

Save diagnostics to file:

```bash
python3 scripts/offline_crps_replay.py --days 30 --output diagnostics.json
```

### 3. Check Tuning Eligibility

Check if you can tune a parameter:

```bash
python3 scripts/parameter_tuning.py check BTC lambda
```

Output:
```
Parameter: BTC / lambda
Current value: 0.94
Eligible: ✅ Yes
Reason: Tuning eligible
Bounds: [0.8, 0.99]
Max step size: ±0.01
```

### 4. Propose Parameter Change

Propose a change (if eligible):

```bash
python3 scripts/parameter_tuning.py propose BTC lambda 0.93 \
    --reason "Short-horizon CRPS analysis suggests lower lambda"
```

### 5. View Current Parameters

List all current parameter values:

```bash
python3 scripts/parameter_tuning.py current
```

### 6. Get Tuning Suggestions

Get suggestions based on diagnostics:

```bash
# First generate diagnostics
python3 scripts/offline_crps_replay.py --days 30 --output diagnostics.json

# Then get suggestions
python3 scripts/parameter_tuning.py suggest --diagnostics-file diagnostics.json
```

## Workflow Example

### Weekly Analysis (Recommended)

```bash
# 1. Replay last 7 days of predictions
python3 scripts/offline_crps_replay.py --days 7 --output weekly_diagnostics.json

# 2. Review diagnostics (printed to console + saved to file)
# 3. Check if tuning is eligible
python3 scripts/parameter_tuning.py check BTC lambda

# 4. If eligible and diagnostics suggest it, propose change
python3 scripts/parameter_tuning.py propose BTC lambda 0.93 \
    --reason "Weekly diagnostics show short-horizon CRPS improved with lower lambda"
```

### Monthly Deep Analysis

```bash
# 1. Replay full month
python3 scripts/offline_crps_replay.py --days 30 --output monthly_diagnostics.json

# 2. Analyze by asset
for asset in BTC ETH SOL XAU; do
    python3 scripts/offline_crps_replay.py --days 30 --asset $asset
done

# 3. Check tuning eligibility for each asset
# 4. Propose changes if warranted
```

## Understanding Diagnostics

### Coverage Rates
- **5%**: Should be ~5% (realized price below 5th percentile 5% of the time)
- **50%**: Should be ~50% (median coverage)
- **95%**: Should be ~95% (realized price below 95th percentile 95% of the time)

**Issues**:
- Coverage too low → distribution too narrow → increase volatility
- Coverage too high → distribution too wide → decrease volatility

### CRPS by Horizon

- **Short (1-5min)**: Early forecast accuracy
  - High CRPS → consider lowering lambda (faster adaptation)
  
- **Medium (15-60min)**: Mid-term accuracy
  - High CRPS → check volatility scaling
  
- **Long (3h/abs)**: Endpoint accuracy
  - High CRPS → check sigma_cap_daily

### Rolling Averages

Shows trend over time. Useful for:
- Detecting performance degradation
- Validating parameter changes
- Comparing assets

## Tuning Guidelines

### When to Tune Lambda

- **Lower lambda** (e.g., 0.94 → 0.93):
  - Short-horizon CRPS is high
  - Need faster volatility adaptation
  
- **Raise lambda** (e.g., 0.93 → 0.94):
  - Too much noise in volatility
  - Need more stable state

### When to Tune df (Student-t degrees of freedom)

- **Lower df** (e.g., 5 → 4):
  - 95% coverage too low (too many breaches)
  - Need fatter tails
  
- **Raise df** (e.g., 4 → 5):
  - 95% coverage too high (too conservative)
  - Distribution too wide

### When to Tune sigma_cap_daily

- **Lower cap** (e.g., 10% → 9%):
  - Absolute endpoint CRPS consistently high
  - Paths too volatile
  
- **Raise cap** (e.g., 9% → 10%):
  - Distribution too narrow
  - Missing extreme moves

**Note**: sigma_cap_daily changes should be quarterly only (very conservative).

## Timing Constraints

- **First 14 days**: No tuning allowed (wait for data)
- **After 14 days**: First tuning eligible
- **Between tunings**: Minimum 30 days
- **After tuning**: 14-day observation period

Example timeline:
```
Day 0:   Miner starts
Day 14:  First tuning eligible ✅
Day 14:  Tune lambda: 0.94 → 0.93
Day 28:  Observation period ends
Day 44:  Next tuning eligible (14 + 30)
```

## Data Locations

- **Predictions**: `data/predictions/YYYY-MM/predictions_YYYY-MM-DD.jsonl`
- **CRPS Results**: `data/crps_results/YYYY-MM/crps_results_YYYY-MM-DD.jsonl`
- **Tuning History**: `data/miner_state/tuning_history.json`
- **Volatility State**: `data/miner_state/volatility_state.json`

## Troubleshooting

### No predictions found
- Check if predictions are being logged (check logs)
- Verify date range includes logged predictions
- Check `data/predictions/` directory

### Cannot fetch realized prices
- Historical price fetching not yet fully implemented
- Requires historical data source integration

### Tuning not eligible
- Check timing constraints (wait for eligibility period)
- One parameter at a time per asset
- Respect observation periods

## Best Practices

1. **Run replay weekly** to catch issues early
2. **Monthly deep analysis** for parameter decisions
3. **Wait for observation periods** before tuning again
4. **Small, incremental changes** (respect step sizes)
5. **Document reasons** for parameter changes
6. **Track results** after tuning to validate improvements
