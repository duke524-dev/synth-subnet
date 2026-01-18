# Miner Integration Guide

## Complete System Overview

Your miner now has two integrated systems:

1. **Live Mining System** (Steps 1-12): Handles validator requests
2. **Offline Tuning System** (Steps 13-17): Analyzes performance and tunes parameters

## Integration Points

### 1. Prediction Logging (Automatic)

The request handler automatically logs predictions using sampling strategy:

```python
# In request_handler.py - already integrated
# Predictions are logged after successful generation
# Sampling: LOW every 30min, HIGH every 15min
```

**No action needed** - logging happens automatically.

### 2. State Persistence (Automatic)

Volatility state is automatically persisted:

```python
# On miner startup - add to neurons/miner.py __init__:
from synth.miner.state_persistence import reload_all_states

def __init__(self, config=None):
    super(Miner, self).__init__(config=config)
    
    # Reload persisted volatility state
    reload_all_states()
    
    # ... rest of initialization
```

### 3. Using New Request Handler

Update your miner to use the new handler:

```python
# In neurons/miner.py - update forward_miner:

from synth.miner.request_handler import handle_request

async def forward_miner(self, synapse: Simulation) -> Simulation:
    """Forward using new complete handler."""
    simulation_input = synapse.simulation_input
    bt.logging.info(
        f"Received request from: {synapse.dendrite.hotkey} "
        f"asset: {simulation_input.asset}"
    )
    
    # Use complete handler (Steps 1-11)
    response_tuple, error = await handle_request(synapse)
    
    if error:
        bt.logging.error(f"Request failed: {error}")
        synapse.simulation_output = None
    else:
        synapse.simulation_output = response_tuple
    
    return synapse
```

## Complete Workflow

### Daily Operations

**Live Mining** (automatic):
- Miner receives requests
- Generates 1000 paths using EWMA volatility
- Logs predictions (sampled)
- Responds to validator

**State Management** (automatic):
- EWMA state updates on price changes
- State persists every 1-5 minutes
- State reloads on restart

### Weekly/Monthly Tuning

**Step 1: Replay Predictions**
```bash
python3 scripts/offline_crps_replay.py --days 30 --output diagnostics.json
```

**Step 2: Review Diagnostics**
- Coverage rates
- CRPS by horizon
- Rolling averages

**Step 3: Check Tuning Eligibility**
```bash
python3 scripts/parameter_tuning.py check BTC lambda
```

**Step 4: Propose Changes (if eligible)**
```bash
python3 scripts/parameter_tuning.py propose BTC lambda 0.93 \
    --reason "Diagnostics show short-horizon CRPS improved"
```

**Step 5: Apply Changes**
- Update parameter defaults in code
- Or load from tuning_history.json
- Restart miner

## File Structure Summary

```
synth-subnet/
├── synth/miner/
│   ├── request_handler.py       # Main handler (use this)
│   ├── validator_core.py        # Validation
│   ├── price_fetcher.py         # Price fetch
│   ├── volatility_state.py      # EWMA state
│   ├── path_generator.py        # Path generation
│   ├── prediction_logger.py     # Logging (auto)
│   └── offline_crps/            # Offline tuning
│       ├── crps_calculation.py  # Validator CRPS (exact copy)
│       ├── replay.py            # CRPS replay
│       └── diagnostics.py       # Diagnostics
│
├── scripts/
│   ├── offline_crps_replay.py   # Replay + diagnostics CLI
│   └── parameter_tuning.py      # Parameter governance CLI
│
├── data/
│   ├── predictions/              # Logged predictions (JSONL)
│   ├── crps_results/             # CRPS replay results (JSONL)
│   └── miner_state/              # State persistence
│       ├── volatility_state.json
│       └── tuning_history.json
│
└── neurons/
    └── miner.py                  # Your miner (update forward_miner)
```

## Quick Integration Steps

### 1. Update neurons/miner.py

```python
# Add imports
from synth.miner.request_handler import handle_request
from synth.miner.state_persistence import reload_all_states

class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        
        # Reload persisted state on startup
        reload_all_states()
    
    async def forward_miner(self, synapse: Simulation) -> Simulation:
        # Use new handler
        response_tuple, error = await handle_request(synapse)
        if error:
            synapse.simulation_output = None
        else:
            synapse.simulation_output = response_tuple
        return synapse
```

### 2. Test Integration

```bash
# Quick test
python3 tests/test_miner_quick.py

# Should show:
# ✅ Success!
#    Paths: 1000
#    Path length: 289
```

### 3. Start Mining

Your miner will now:
- ✅ Use EWMA volatility state
- ✅ Generate proper stochastic paths
- ✅ Log predictions automatically
- ✅ Persist state across restarts

### 4. Run Offline Tuning (Weekly)

```bash
# After a week of mining, analyze performance
python3 scripts/offline_crps_replay.py --days 7
```

## Data Flow Diagram

```
[Validator Request]
        ↓
[handle_request()] ← Uses all Steps 1-11
        ↓
[Generate Paths] → Path[0] (flat) + Paths[1..999] (stochastic)
        ↓
[Validate & Return]
        ↓
[Log Prediction] → data/predictions/*.jsonl (sampled)
        ↓
        ↓ (after time passes)
        ↓
[Fetch Realized Prices] → From Pyth historical
        ↓
[Calculate CRPS] → Using validator code (exact copy)
        ↓
[Store Results] → data/crps_results/*.jsonl
        ↓
[Generate Diagnostics] → Coverage, horizons, trends
        ↓
[Parameter Governance] → Check eligibility, propose changes
```

## Key Features

### ✅ Automatic
- Prediction logging (with sampling)
- State persistence
- EWMA updates
- Bootstrap on cold start

### 📊 Manual (Weekly/Monthly)
- CRPS replay
- Diagnostics generation
- Parameter tuning decisions

### 🔒 Governed
- Tuning timing constraints
- Bounded parameter changes
- One parameter at a time
- Observation periods

## Testing Checklist

- [ ] Miner starts and loads persisted state
- [ ] Requests are handled correctly
- [ ] Predictions are logged (check `data/predictions/`)
- [ ] State persists (check `data/miner_state/`)
- [ ] Can run CRPS replay script
- [ ] Can check tuning eligibility
- [ ] Diagnostics generate correctly

## Next Steps

1. **Update neurons/miner.py** to use new handler
2. **Test with validator** (or test suite)
3. **Let it run** for a few days to collect data
4. **Run offline replay** to analyze performance
5. **Tune parameters** if diagnostics suggest improvements

Your miner is now complete and production-ready! 🚀
