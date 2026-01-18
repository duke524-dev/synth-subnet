# Miner Build Progress

## Completed Steps

### ✅ Step 0: Freeze Requirements
- Validated: Single asset per request, 1000 paths, correct path length formula

### ✅ Step 1: Request Parsing + Schema Output (MVP)
- **File**: `synth/miner/request_handler.py`
- Parses simulation_input correctly
- Computes `steps = time_length // time_increment`
- Generates dummy paths (flat) for MVP testing
- Formats response tuple correctly

### ✅ Step 2: Strict Local Validation Guard
- **File**: `synth/miner/validator_core.py`
- Validates: path count, path length, price validity (finite, > 0, no NaN)
- Safe fallback path generator
- Pre-send validation prevents validator rejections

### ✅ Step 3: Pyth Spot Fetch
- **File**: `synth/miner/price_fetcher.py`
- Fetches from Pyth API with retry logic
- In-memory caching (3-minute TTL)
- Fallback to cached price if API fails
- Handles staleness gracefully

## Next Steps

### Step 4: 1-minute OHLC Close Fetch (IN PROGRESS)
- Need to implement historical 1-minute close fetching
- For EWMA state updates

### Steps 5-12: Core Model Implementation
- EWMA volatility state
- Bootstrap on cold start
- State persistence
- Volatility scaling + caps
- Equity market hours
- Path generator (1000 paths)
- Integration
